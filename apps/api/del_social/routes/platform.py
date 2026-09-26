"""Platform-admin operations: creating tenants and issuing password-reset links (ADR 002).

Being a platform admin gives no access to any tenant's data; these routes only
create a tenant with its first owner invitation, or a reset link for an account.
"""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.db import set_account, set_tenant
from del_social.core.deps import CurrentAccount, get_db, require_platform_admin
from del_social.core.security import new_token
from del_social.models import MemberRole, PasswordReset, Tenant
from del_social.tenants.service import (
    PASSWORD_RESET_TTL,
    app_link,
    create_invitation,
    normalize_email,
)

router = APIRouter(prefix="/platform", tags=["platform"])


class TenantCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    owner_email: str = Field(max_length=254)


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
