import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class MemberRole(enum.StrEnum):
    """Per-tenant roles. Platform admin is a flag on Account, not a tenant role."""

    OWNER = "owner"
    ADMIN = "admin"
    APPROVER = "approver"
    VIEWER = "viewer"


member_role_type = Enum(
    MemberRole, name="member_role", values_callable=lambda e: [m.value for m in e]
)


class Membership(Base):
    """An account's access to one tenant, with its role there. RLS: tenant-scoped."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "account_id", name="uq_memberships_tenant_account"),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="RESTRICT"), index=True
    )
    role: Mapped[MemberRole] = mapped_column(
        member_role_type, server_default=MemberRole.VIEWER.value
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
