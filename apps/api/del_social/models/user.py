import enum
import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class UserRole(enum.StrEnum):
    """Per-tenant roles. Platform superadmin is not a tenant role and lives elsewhere."""

    OWNER = "owner"
    ADMIN = "admin"
    APPROVER = "approver"
    VIEWER = "viewer"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT")
    )
    email: Mapped[str] = mapped_column(Text)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        server_default=UserRole.VIEWER.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
