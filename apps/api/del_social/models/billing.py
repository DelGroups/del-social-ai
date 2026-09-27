import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class Plan(Base):
    """A package from the catalog (Basic / Pro / Enterprise). Global, read-only for the app. NULL limit = unlimited."""

    __tablename__ = "plans"

    plan_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    price_azn: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    posts_per_month: Mapped[int | None] = mapped_column(Integer)
    draft_factor: Mapped[int] = mapped_column(Integer, server_default="3")
    channels: Mapped[int | None] = mapped_column(Integer)
    users: Mapped[int | None] = mapped_column(Integer)
    video_credits: Mapped[int | None] = mapped_column(Integer)
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    sort: Mapped[int] = mapped_column(Integer, server_default="0")
    active: Mapped[bool] = mapped_column(server_default=text("true"))


class Subscription(Base):
    """The plan a company is on. One active row per company. RLS: tenant."""

    __tablename__ = "subscriptions"

    subscription_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.tenant_id", ondelete="RESTRICT"))
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.plan_id", ondelete="RESTRICT"))
    status: Mapped[str] = mapped_column(Text, server_default="active")
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    extra_video_credits: Mapped[int] = mapped_column(Integer, server_default="0")
    note: Mapped[str] = mapped_column(Text, server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PlanRequest(Base):
    """An owner asks for another plan; the platform admin handles it. RLS: tenant."""

    __tablename__ = "plan_requests"

    request_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.tenant_id", ondelete="RESTRICT"))
    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.plan_id", ondelete="RESTRICT"))
    message: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(Text, server_default="open")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
