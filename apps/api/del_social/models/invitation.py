import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, LargeBinary, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base
from del_social.models.membership import MemberRole, member_role_type


class Invitation(Base):
    """One-time link to join a tenant (ADR 002). Only the token's SHA-256 is stored."""

    __tablename__ = "invitations"
    __table_args__ = (
        CheckConstraint("email = lower(email)", name="ck_invitations_email_lowercase"),
        CheckConstraint("octet_length(token_hash) = 32", name="ck_invitations_token_hash_len"),
        Index(
            "uq_invitations_pending",
            "tenant_id",
            "email",
            unique=True,
            postgresql_where=text("accepted_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    invitation_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT")
    )
    email: Mapped[str] = mapped_column(Text)
    role: Mapped[MemberRole] = mapped_column(member_role_type)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="SET NULL")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
