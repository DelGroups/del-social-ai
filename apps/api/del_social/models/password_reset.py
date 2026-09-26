import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, LargeBinary, func, text
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class PasswordReset(Base):
    """One-time reset link issued by a platform admin (ADR 002). Only the token's SHA-256 is stored."""

    __tablename__ = "password_resets"
    __table_args__ = (
        CheckConstraint(
            "octet_length(token_hash) = 32", name="ck_password_resets_token_hash_len"
        ),
    )

    reset_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, unique=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
