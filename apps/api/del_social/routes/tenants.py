"""Members and invitations of one tenant. Every route re-checks membership and role (ADR 002)."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.deps import TenantContext, get_db, require_permission
from del_social.models import Invitation, MemberRole, Membership
from del_social.tenants.permissions import Permission, has_permission
from del_social.tenants.service import create_invitation, ensure_another_owner, normalize_email

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["tenants"])

can_view = require_permission(Permission.VIEW)
can_manage_members = require_permission(Permission.MANAGE_MEMBERS)


class MemberOut(BaseModel):
    membership_id: uuid.UUID
    account_id: uuid.UUID
    email: str
    role: MemberRole
    created_at: datetime


class RoleChangeIn(BaseModel):
    role: MemberRole


class InviteIn(BaseModel):
    email: str = Field(max_length=254)
    role: MemberRole


class InvitationOut(BaseModel):
    invitation_id: uuid.UUID
    email: str
    role: MemberRole
    created_at: datetime
    expires_at: datetime


class InvitationCreatedOut(InvitationOut):
    url: str  # shown once; only its hash is stored


def _require_owner_rights_if(ctx: TenantContext, touches_owner: bool) -> None:
    if touches_owner and not has_permission(ctx.role, Permission.MANAGE_OWNERS):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only owners can manage owners")


async def _get_membership(db: AsyncSession, membership_id: uuid.UUID) -> Membership:
    membership = await db.get(Membership, membership_id)  # RLS: only this tenant's rows exist
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return membership


# --- members ---


@router.get("/members", response_model=list[MemberOut])
async def list_members(
    ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)
) -> list[MemberOut]:
    rows = (await db.execute(text("SELECT * FROM auth_tenant_members()"))).all()
    return [MemberOut.model_validate(r, from_attributes=True) for r in rows]


@router.patch("/members/{membership_id}", response_model=MemberOut)
async def change_role(
    membership_id: uuid.UUID,
    body: RoleChangeIn,
    ctx: TenantContext = Depends(can_manage_members),
    db: AsyncSession = Depends(get_db),
) -> MemberOut:
    membership = await _get_membership(db, membership_id)
    _require_owner_rights_if(ctx, MemberRole.OWNER in (membership.role, body.role))
    if membership.role == MemberRole.OWNER and body.role != MemberRole.OWNER:
        await ensure_another_owner(db, excluding=membership_id)
    membership.role = body.role
    await db.flush()
    row = (
        await db.execute(
            text("SELECT * FROM auth_tenant_members() WHERE membership_id = :m"), {"m": membership_id}
        )
    ).one()
    return MemberOut.model_validate(row, from_attributes=True)


@router.delete("/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    membership_id: uuid.UUID,
    ctx: TenantContext = Depends(can_manage_members),
    db: AsyncSession = Depends(get_db),
) -> None:
    membership = await _get_membership(db, membership_id)
    _require_owner_rights_if(ctx, membership.role == MemberRole.OWNER)
    if membership.role == MemberRole.OWNER:
        await ensure_another_owner(db, excluding=membership_id)
    await db.delete(membership)


# --- invitations ---


@router.post("/invitations", response_model=InvitationCreatedOut, status_code=status.HTTP_201_CREATED)
async def invite(
    body: InviteIn,
    ctx: TenantContext = Depends(can_manage_members),
    db: AsyncSession = Depends(get_db),
) -> InvitationCreatedOut:
    email = normalize_email(body.email)
    _require_owner_rights_if(ctx, body.role == MemberRole.OWNER)
    already_member = await db.scalar(
        text("SELECT count(*) FROM auth_tenant_members() WHERE email = :e"), {"e": email}
    )
    if already_member:
        raise HTTPException(status.HTTP_409_CONFLICT, "This person is already a member")
    invitation, url = await create_invitation(
        db, ctx.tenant_id, email, body.role, invited_by=ctx.account.account_id
    )
    await db.refresh(invitation)
    return InvitationCreatedOut.model_validate({**_invitation_fields(invitation), "url": url})


@router.get("/invitations", response_model=list[InvitationOut])
async def list_invitations(
    ctx: TenantContext = Depends(can_manage_members), db: AsyncSession = Depends(get_db)
) -> list[InvitationOut]:
    """Pending invitations only. Links are never shown again after creation."""
    invitations = (
        await db.scalars(
            select(Invitation)
            .where(
                Invitation.accepted_at.is_(None),
                Invitation.revoked_at.is_(None),
                Invitation.expires_at > func.now(),
            )
            .order_by(Invitation.created_at)
        )
    ).all()
    return [InvitationOut.model_validate(_invitation_fields(i)) for i in invitations]


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: uuid.UUID,
    ctx: TenantContext = Depends(can_manage_members),
    db: AsyncSession = Depends(get_db),
) -> None:
    invitation = await db.get(Invitation, invitation_id)  # RLS: this tenant only
    if invitation is None or invitation.accepted_at or invitation.revoked_at:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No pending invitation with this id")
    _require_owner_rights_if(ctx, invitation.role == MemberRole.OWNER)
    await db.execute(
        update(Invitation)
        .where(Invitation.invitation_id == invitation_id)
        .values(revoked_at=func.now())
    )


def _invitation_fields(invitation: Invitation) -> dict:
    return {
        "invitation_id": invitation.invitation_id,
        "email": invitation.email,
        "role": invitation.role,
        "created_at": invitation.created_at,
        "expires_at": invitation.expires_at,
    }
