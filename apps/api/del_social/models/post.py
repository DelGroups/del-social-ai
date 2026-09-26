import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Text, Uuid, func, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class Post(Base):
    """One post: photos + caption options → a human picks and approves → published per channel.

    status: generating → ready | failed → approved → publishing → published | partly_published
            (archived: hidden). RLS: tenant. No DELETE for del_app.
    """

    __tablename__ = "posts"

    post_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.tenant_id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(Text, server_default="generating")
    product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("products.product_id", ondelete="RESTRICT"))
    asset_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(Uuid()))
    format: Mapped[str] = mapped_column(Text, server_default="feed")
    with_logo: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    channels: Mapped[list[str]] = mapped_column(ARRAY(Text))
    notes: Mapped[str] = mapped_column(Text, server_default="")
    brief: Mapped[dict | None] = mapped_column(JSONB)
    generation: Mapped[dict | None] = mapped_column(JSONB)
    chosen_option: Mapped[int | None] = mapped_column(Integer)
    caption: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    results: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))  # channel → {id, url} or {error}
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
