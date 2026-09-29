"""Platform-admin operations: creating tenants and issuing password-reset links (ADR 002).

Being a platform admin gives no access to any tenant's data; these routes only
create a tenant with its first owner invitation, issue a reset link for an account, and
manage packages: billing aggregates per company (plan, usage counts, AI cost), no content (ADR 007).
"""
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.db import set_account, set_tenant
from del_social.core.deps import CurrentAccount, get_db, require_platform_admin
from del_social.core.security import new_token
from del_social.billing import credits
from del_social.models import (
    Addon,
    CreditPack,
    MemberRole,
    PasswordReset,
    Plan,
    PlanRequest,
    PurchaseRequest,
    Subscription,
    Tenant,
    TenantAddon,
)
from del_social.tenants.service import (
    PASSWORD_RESET_TTL,
    app_link,
    create_invitation,
    normalize_email,
)

router = APIRouter(prefix="/platform", tags=["platform"])


AZN_PER_USD = Decimal("1.7")  # rate used in the commercial proposal, for the margin estimate
MONTH = timedelta(days=30)


class TenantCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    owner_email: str = Field(max_length=254)
    plan_id: str | None = Field(default="basic", max_length=40)  # None = no social package (YouTube Studio only)
    months: int | None = Field(default=1, ge=1, le=36)  # None = no end date
    addons: list[str] = Field(default_factory=list, max_length=5)


class TenantCreatedOut(BaseModel):
    tenant_id: uuid.UUID
    name: str
    owner_invitation_url: str
    invitation_expires_at: datetime


class ResetCreateIn(BaseModel):
    email: str = Field(max_length=254)


class ResetCreatedOut(BaseModel):
    url: str
    expires_at: datetime


@router.post("/tenants", response_model=TenantCreatedOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    body: TenantCreateIn,
    admin: CurrentAccount = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> TenantCreatedOut:
    owner_email = normalize_email(body.owner_email)
    tenant_id = uuid.uuid4()
    await set_tenant(db, tenant_id)  # RLS: the new row must match the context
    db.add(Tenant(tenant_id=tenant_id, name=body.name.strip()))
    await db.flush()
    if body.plan_id:
        await _assign(db, tenant_id, body.plan_id, body.months, 0, "Created with the company", admin.account_id)
    for addon_id in body.addons:
        await _set_addon(db, tenant_id, addon_id, True, body.months, "Created with the company", admin.account_id)
    invitation, url = await create_invitation(
        db, tenant_id, owner_email, MemberRole.OWNER, invited_by=admin.account_id
    )
    return TenantCreatedOut(
        tenant_id=tenant_id,
        name=body.name.strip(),
        owner_invitation_url=url,
        invitation_expires_at=invitation.expires_at,
    )


@router.post(
    "/password-resets", response_model=ResetCreatedOut, status_code=status.HTTP_201_CREATED
)
async def issue_password_reset(
    body: ResetCreateIn,
    admin: CurrentAccount = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> ResetCreatedOut:
    """Only platform admins may do this: an account can belong to several tenants,
    so a tenant admin issuing resets could take over access to other tenants."""
    email = normalize_email(body.email)
    target = (
        await db.execute(text("SELECT account_id FROM auth_login_lookup(:e)"), {"e": email})
    ).first()
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No account with this email")
    token, token_hash = new_token()
    expires_at = datetime.now(UTC) + PASSWORD_RESET_TTL
    await set_account(db, target.account_id)  # RLS: resets are scoped to their account
    db.add(
        PasswordReset(
            account_id=target.account_id,
            token_hash=token_hash,
            created_by=admin.account_id,
            expires_at=expires_at,
        )
    )
    await db.flush()
    return ResetCreatedOut(url=app_link(f"/reset-password/{token}"), expires_at=expires_at)


async def _assign(
    db: AsyncSession, tenant_id: uuid.UUID, plan_id: str, months: int | None, extra_video: int, note: str,
    by: uuid.UUID,
) -> Subscription:
    """End the current package and start a new one now (a new monthly window). Tenant context must be set."""
    plan = await db.get(Plan, plan_id)
    if plan is None or not plan.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such package")
    now = datetime.now(UTC)
    for old in (await db.scalars(select(Subscription).where(Subscription.status == "active"))).all():
        old.status = "ended"
    await db.flush()
    sub = Subscription(
        subscription_id=uuid.uuid4(), tenant_id=tenant_id, plan_id=plan.plan_id, status="active", starts_at=now,
        expires_at=now + MONTH * months if months else None, extra_video_credits=extra_video, note=note, created_by=by,
    )
    db.add(sub)
    for req in (await db.scalars(select(PlanRequest).where(PlanRequest.status == "open"))).all():
        req.status = "done"
    await db.flush()
    return sub


class TenantOverview(BaseModel):
    tenant_id: uuid.UUID
    name: str
    created_at: datetime
    plan_id: str | None
    price_azn: Decimal | None
    starts_at: datetime | None
    expires_at: datetime | None
    extra_video_credits: int | None
    period_start: datetime | None
    period_end: datetime | None
    posts_published: int
    posts_scheduled: int
    posts_limit: int | None
    members: int
    channels: int
    ai_cost_month_usd: Decimal
    margin_month_usd: Decimal | None  # price in USD minus this month's AI cost (estimate)
    open_request_plan: str | None
    open_request_at: datetime | None


@router.get("/tenants", response_model=list[TenantOverview])
async def list_tenants(
    admin: CurrentAccount = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)
) -> list[TenantOverview]:
    """Every company with its package, this month's usage and AI cost (billing numbers only)."""
    await set_account(db, admin.account_id)  # the function checks the caller is a platform admin
    plans = {p.plan_id: p for p in (await db.scalars(select(Plan))).all()}
    rows = (await db.execute(text("SELECT * FROM platform_tenant_overview()"))).mappings().all()
    out = []
    for r in rows:
        plan = plans.get(r["plan_id"]) if r["plan_id"] else None
        cost = Decimal(r["ai_cost_month_usd"] or 0)
        out.append(TenantOverview(
            **{k: r[k] for k in ("tenant_id", "name", "created_at", "plan_id", "starts_at", "expires_at", "extra_video_credits",
                                 "period_start", "period_end", "posts_published", "posts_scheduled", "members", "channels",
                                 "open_request_plan", "open_request_at")},
            price_azn=plan.price_azn if plan else None, posts_limit=plan.posts_per_month if plan else None,
            ai_cost_month_usd=cost.quantize(Decimal("0.0001")),
            margin_month_usd=(plan.price_azn / AZN_PER_USD - cost).quantize(Decimal("0.01")) if plan else None,
        ))
    return out


class SubscriptionIn(BaseModel):
    plan_id: str = Field(min_length=1, max_length=40)
    months: int | None = Field(default=1, ge=1, le=36)  # None = no end date
    extra_video_credits: int = Field(default=0, ge=0, le=1000)
    note: str = Field(default="", max_length=500)


class SubscriptionOut(BaseModel):
    plan_id: str
    starts_at: datetime
    expires_at: datetime | None
    extra_video_credits: int


@router.put("/tenants/{tenant_id}/subscription", response_model=SubscriptionOut)
async def assign_plan(
    tenant_id: uuid.UUID,
    body: SubscriptionIn,
    admin: CurrentAccount = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionOut:
    """Assign, renew or upgrade a company's package (manual until online payment, phase 5)."""
    await set_tenant(db, tenant_id)  # RLS: only this company's package rows
    if await db.get(Tenant, tenant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such company")
    sub = await _assign(db, tenant_id, body.plan_id, body.months, body.extra_video_credits, body.note.strip(), admin.account_id)
    return SubscriptionOut(plan_id=sub.plan_id, starts_at=sub.starts_at, expires_at=sub.expires_at,
                           extra_video_credits=sub.extra_video_credits)


async def _set_addon(
    db: AsyncSession, tenant_id: uuid.UUID, addon_id: str, active: bool, months: int | None, note: str, by: uuid.UUID,
) -> TenantAddon | None:
    """Turn an add-on on (a new monthly window from now) or off. Tenant context must be set."""
    addon = await db.get(Addon, addon_id)
    if addon is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such add-on")
    for old in (await db.scalars(select(TenantAddon).where(TenantAddon.addon_id == addon_id, TenantAddon.status == "active"))).all():
        old.status = "ended"
    await db.flush()
    row = None
    if active:
        now = datetime.now(UTC)
        row = TenantAddon(tenant_addon_id=uuid.uuid4(), tenant_id=tenant_id, addon_id=addon_id, status="active", starts_at=now,
                          expires_at=now + MONTH * months if months else None, note=note, created_by=by)
        db.add(row)
    for req in (await db.scalars(select(PurchaseRequest).where(PurchaseRequest.status == "open", PurchaseRequest.kind == "addon"))).all():
        req.status = "done"
    await db.flush()
    return row


class AddonIn(BaseModel):
    active: bool
    months: int | None = Field(default=1, ge=1, le=36)
    note: str = Field(default="", max_length=500)


class AddonOut(BaseModel):
    addon_id: str
    active: bool
    starts_at: datetime | None
    expires_at: datetime | None


@router.put("/tenants/{tenant_id}/addons/{addon_id}", response_model=AddonOut)
async def set_addon(
    tenant_id: uuid.UUID, addon_id: str, body: AddonIn,
    admin: CurrentAccount = Depends(require_platform_admin), db: AsyncSession = Depends(get_db),
) -> AddonOut:
    await set_tenant(db, tenant_id)
    if await db.get(Tenant, tenant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such company")
    row = await _set_addon(db, tenant_id, addon_id, body.active, body.months, body.note.strip(), admin.account_id)
    return AddonOut(addon_id=addon_id, active=row is not None, starts_at=row.starts_at if row else None,
                    expires_at=row.expires_at if row else None)


class CreditsIn(BaseModel):
    credits: int | None = Field(default=None, ge=1, le=100_000)
    pack_id: str | None = Field(default=None, max_length=40)  # or a pack from the catalog
    addon_id: str = Field(default="youtube", max_length=40)
    note: str = Field(default="", max_length=500)


class CreditsOut(BaseModel):
    granted: int
    total: int


@router.post("/tenants/{tenant_id}/credits", response_model=CreditsOut, status_code=status.HTTP_201_CREATED)
async def grant_credits(
    tenant_id: uuid.UUID, body: CreditsIn,
    admin: CurrentAccount = Depends(require_platform_admin), db: AsyncSession = Depends(get_db),
) -> CreditsOut:
    """Credits the company bought (paid outside the app until phase 5). They never expire."""
    await set_tenant(db, tenant_id)
    if await db.get(Tenant, tenant_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such company")
    amount, note = body.credits, body.note.strip()
    if body.pack_id:
        pack = await db.get(CreditPack, body.pack_id)
        if pack is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No such credit pack")
        amount, note = pack.credits, note or f"Pack {pack.pack_id} ({pack.price_azn} AZN)"
    if not amount:
        raise HTTPException(422, "Give a number of credits or a pack")
    await credits.grant(db, tenant_id, amount, "purchase", admin.account_id, note, body.addon_id)
    for req in (await db.scalars(select(PurchaseRequest).where(PurchaseRequest.status == "open", PurchaseRequest.kind == "credits"))).all():
        req.status = "done"
    await db.flush()
    return CreditsOut(granted=amount, total=(await credits.balance(db, body.addon_id)).total)


class AddonOverview(BaseModel):
    tenant_id: uuid.UUID
    addon_id: str
    status: str
    starts_at: datetime
    expires_at: datetime | None
    purchased_balance: int
    monthly_spent: int
    open_requests: int


@router.get("/addons", response_model=list[AddonOverview])
async def list_addons(
    admin: CurrentAccount = Depends(require_platform_admin), db: AsyncSession = Depends(get_db)
) -> list[AddonOverview]:
    await set_account(db, admin.account_id)
    rows = (await db.execute(text("SELECT * FROM platform_addon_overview()"))).mappings().all()
    return [AddonOverview(**r) for r in rows]
