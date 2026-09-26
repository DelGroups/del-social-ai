import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class MediaAsset(Base):
    """An uploaded photo or the company logo. The file lives on the media volume. RLS: tenant.

    Deleting is soft (deleted_at) for del_app; the files are removed from disk.
    """

    __tablename__ = "media_assets"

    asset_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.tenant_id", ondelete="RESTRICT"))
    kind: Mapped[str] = mapped_column(Text)  # photo | logo
    filename: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(Text)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(Text)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    description: Mapped[str] = mapped_column(Text, server_default="")  # what the photo shows (briefs use it)
    focal_x: Mapped[float] = mapped_column(Float, server_default="0.5")
    focal_y: Mapped[float] = mapped_column(Float, server_default="0.5")
    enhance: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
