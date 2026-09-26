import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class Channel(enum.StrEnum):
    INSTAGRAM = "instagram"
    FACEBOOK = "facebook"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    TIKTOK = "tiktok"
    YOUTUBE = "youtube"


class ConnectionStatus(enum.StrEnum):
    ACTIVE = "active"
    ERROR = "error"  # last check failed (token revoked, permissions removed, ...)


class Connection(Base):
    """One connected channel account (a Facebook page, an Instagram account, a bot). RLS: tenant-scoped.

    The access token is stored only as vault ciphertext (ADR 003) and never leaves the API.
    """

    __tablename__ = "connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", "external_id", name="uq_connections_tenant_channel_external"),
    )

    connection_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT")
    )
    channel: Mapped[str] = mapped_column(Text)
    external_id: Mapped[str] = mapped_column(Text)  # page id, Instagram user id, bot id
    display_name: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default=ConnectionStatus.ACTIVE.value)
    token_ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))  # non-secret
    connected_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("accounts.account_id", ondelete="SET NULL")
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
