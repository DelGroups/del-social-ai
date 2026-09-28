"""A company's package: what it includes, what is used this month, and asking for an upgrade (ADR 007).

Shows allowances and credits, never the AI cost in dollars (that is for the platform admin only).
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.billing import credits, quota
from del_social.core.deps import TenantContext, get_db, require_permission
from del_social.models import Addon, CreditEntry, CreditPack, Plan, PlanRequest, PurchaseRequest
from del_social.tenants.permissions import Permission

router = APIRouter(prefix="/tenants/{tenant_id}/plan", tags=["plan"])

can_view = require_permission(Permission.VIEW)
can_buy = require_permission(Permission.MANAGE_TENANT)  # owners: billing


class PlanInfo(BaseModel):
    plan_id: str
    name: str
    price_azn: Decimal
    posts_per_month: int | None  # None = unlimited
    channels: int | None
    users: int | None
    video_credits: int | None
    features: dict[str, Any]


class Meter(BaseModel):
    used: int
    limit: int | None  # None = unlimited


class RequestInfo(BaseModel):
    plan_id: str
    created_at: datetime


class PackInfo(BaseModel):
    pack_id: str
    credits: int
    price_azn: Decimal


class CreditMove(BaseModel):
    delta: int
    reason: str
    created_at: datetime


class AddonStatus(BaseModel):
    addon_id: str
    name: str
    price_azn: Decimal
    monthly_credits: int
    active: bool
    starts_at: datetime | None
    expires_at: datetime | None
    period_end: datetime | None  # when the monthly credits renew
    monthly_left: int
    purchased: int  # bought credits left (never expire)
    total: int
    packs: list[PackInfo]
    history: list[CreditMove]
    open_request: str | None  # the item asked for (add-on or pack), waiting for the platform admin
    costs: dict[str, int]  # credits per piece of work (billing/credits.py)


class PlanStatus(BaseModel):
    state: str  # none | expired | limit | warning | ok
    plan: PlanInfo | None
    starts_at: datetime | None
    expires_at: datetime | None
    period_start: datetime | None
    period_end: datetime | None
    posts: Meter  # published + approved and waiting for their time
    posts_published: int
    posts_scheduled: int
    drafts: Meter
    channels: Meter
    users: Meter
    video: Meter
    catalog: list[PlanInfo]
    open_request: RequestInfo | None
    addons: list[AddonStatus]


async def addon_statuses(db: AsyncSession) -> list[AddonStatus]:
    out = []
    for addon in (await db.scalars(select(Addon).where(Addon.active).order_by(Addon.sort))).all():
        b = await credits.balance(db, addon.addon_id)
        packs = (await db.scalars(select(CreditPack).where(CreditPack.addon_id == addon.addon_id, CreditPack.active)
                                  .order_by(CreditPack.sort))).all()
        moves = (await db.scalars(select(CreditEntry).where(CreditEntry.addon_id == addon.addon_id)
                                  .order_by(CreditEntry.created_at.desc()).limit(20))).all()
        req = await db.scalar(select(PurchaseRequest).where(PurchaseRequest.status == "open")
                              .order_by(PurchaseRequest.created_at.desc()).limit(1))
        sub = b.subscription
        out.append(AddonStatus(
            addon_id=addon.addon_id, name=addon.name, price_azn=addon.price_azn, monthly_credits=addon.monthly_credits,
            active=b.active, starts_at=sub.starts_at if sub else None, expires_at=sub.expires_at if sub else None,
            period_end=b.period_end, monthly_left=b.monthly_left if b.active else 0, purchased=max(0, b.purchased),
            total=b.total if b.active else 0,
            packs=[PackInfo(pack_id=k.pack_id, credits=k.credits, price_azn=k.price_azn) for k in packs],
            history=[CreditMove(delta=m.delta, reason=m.reason, created_at=m.created_at) for m in moves],
            open_request=req.item_id if req else None, costs=dict(credits.COST),
        ))
    return out


def plan_info(p: Plan) -> PlanInfo:
    return PlanInfo.model_validate(p, from_attributes=True)


async def plan_status(db: AsyncSession) -> PlanStatus:
    a = await quota.allowance(db)
    catalog = (await db.scalars(select(Plan).where(Plan.active).order_by(Plan.sort))).all()
    req = await db.scalar(select(PlanRequest).where(PlanRequest.status == "open").order_by(PlanRequest.created_at.desc()).limit(1))
    s = a.subscription
    return PlanStatus(
        state=a.state, plan=plan_info(a.plan) if a.plan else None,
        starts_at=s.starts_at if s else None, expires_at=s.expires_at if s else None,
        period_start=a.period_start, period_end=a.period_end,
        posts=Meter(used=a.posts_used, limit=a.posts_limit), posts_published=a.posts_published, posts_scheduled=a.posts_scheduled,
        drafts=Meter(used=a.drafts, limit=a.drafts_limit), channels=Meter(used=a.channels, limit=a.channels_limit),
        users=Meter(used=a.users, limit=a.users_limit), video=Meter(used=a.video_used, limit=a.video_limit),
        catalog=[plan_info(p) for p in catalog],
        open_request=RequestInfo(plan_id=req.plan_id, created_at=req.created_at) if req else None,
        addons=await addon_statuses(db),
    )


@router.get("", response_model=PlanStatus)
async def get_plan(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> PlanStatus:
    return await plan_status(db)


class UpgradeIn(BaseModel):
    plan_id: str = Field(min_length=1, max_length=40)
    message: str = Field(default="", max_length=1000)


@router.post("/requests", response_model=PlanStatus, status_code=status.HTTP_201_CREATED)
async def request_plan(body: UpgradeIn, ctx: TenantContext = Depends(can_buy), db: AsyncSession = Depends(get_db)) -> PlanStatus:
    """Ask for another package. The platform admin assigns it (online payment comes in phase 5)."""
    plan = await db.get(Plan, body.plan_id)
    if plan is None or not plan.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such package")
    for old in (await db.scalars(select(PlanRequest).where(PlanRequest.status == "open"))).all():
        old.status = "done"  # the newest request replaces an earlier one
    db.add(PlanRequest(
        request_id=uuid.uuid4(), tenant_id=ctx.tenant_id, plan_id=plan.plan_id, message=body.message.strip(),
        requested_by=ctx.account.account_id,
    ))
    await db.flush()
    return await plan_status(db)


class PurchaseIn(BaseModel):
    kind: str = Field(pattern="^(addon|credits)$")
    item_id: str = Field(min_length=1, max_length=40)
    message: str = Field(default="", max_length=1000)


@router.post("/purchases", response_model=PlanStatus, status_code=status.HTTP_201_CREATED)
async def request_purchase(body: PurchaseIn, ctx: TenantContext = Depends(can_buy), db: AsyncSession = Depends(get_db)) -> PlanStatus:
    """Ask for an add-on or a credit pack; the platform admin turns it on (ADR 012)."""
    item = await db.get(Addon if body.kind == "addon" else CreditPack, body.item_id)
    if item is None or not item.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such item")
    for old in (await db.scalars(select(PurchaseRequest).where(PurchaseRequest.status == "open"))).all():
        old.status = "done"
    db.add(PurchaseRequest(request_id=uuid.uuid4(), tenant_id=ctx.tenant_id, kind=body.kind, item_id=body.item_id,
                           message=body.message.strip(), requested_by=ctx.account.account_id))
    await db.flush()
    return await plan_status(db)
