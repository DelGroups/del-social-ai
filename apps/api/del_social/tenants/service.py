"""Tenant-side operations shared by the tenant and platform routes."""
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.config import get_settings
from del_social.core.security import new_token
from del_social.models import Invitation, MemberRole, Membership

INVITATION_TTL = timedelta(days=7)
PASSWORD_RESET_TTL = timedelta(hours=1)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def normalize_email(raw: str) -> str:
    email = raw.strip().lower()
    if len(email) > 254 or not _EMAIL_RE.match(email):
        raise HTTPException(422, "Invalid email address")
    return email


def app_link(path: str) -> str:
    return get_settings().app_base_url.rstrip("/") + path


async def create_invitation(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    email: str,
    role: MemberRole,
    invited_by: uuid.UUID | None,
) -> tuple[Invitation, str]:
    """Create an invitation in the current tenant context. Returns it and its one-time link."""
    token, token_hash = new_token()
    invitation = Invitation(
        tenant_id=tenant_id,
        email=email,
        role=role,
        token_hash=token_hash,
        invited_by=invited_by,
        expires_at=datetime.now(UTC) + INVITATION_TTL,
    )
    db.add(invitation)
    try:
        async with db.begin_nested():
            await db.flush()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This person already has a pending invitation"
        ) from None
    return invitation, app_link(f"/invite/{token}")


async def ensure_another_owner(db: AsyncSession, excluding: uuid.UUID) -> None:
    """A tenant must always keep at least one owner. Locks owner rows against races."""
    owners = (
        await db.scalars(
            select(Membership.membership_id)
            .where(Membership.role == MemberRole.OWNER)
            .with_for_update()
        )
    ).all()
    if not [o for o in owners if o != excluding]:
        raise HTTPException(status.HTTP_409_CONFLICT, "A tenant must keep at least one owner")
