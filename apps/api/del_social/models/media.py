import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
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
    # own | render (visualisation) | licensed | reference (inspiration only, never published)
    source: Mapped[str] = mapped_column(Text, server_default="own")
    parent_asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("media_assets.asset_id", ondelete="RESTRICT"))
    edit: Mapped[dict | None] = mapped_column(JSONB)  # AI edit: kind, request, prompt, model, cost_usd, error
    status: Mapped[str] = mapped_column(Text, server_default="ready")  # pending | ready | failed
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # AI edits need a human OK
    edit_recipe: Mapped[dict | None] = mapped_column(JSONB)  # this photo's own AI edit settings
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.product_id", ondelete="RESTRICT"))
    position: Mapped[int] = mapped_column(Integer, server_default="0")  # order within the product
    default_logo: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))  # the logo put on posts
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
