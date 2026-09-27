import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Integer, Numeric, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class Competitor(Base):
    """An account the Market Researcher watches: named by the owner or found by the team. RLS: tenant."""

    __tablename__ = "competitors"

    competitor_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.tenant_id", ondelete="RESTRICT"))
    username: Mapped[str] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text)  # owner | discovered
    status: Mapped[str] = mapped_column(Text, server_default="active")  # active | invalid | inactive | ignored
    followers: Mapped[int | None] = mapped_column(Integer)
    last_post_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    note: Mapped[str] = mapped_column(Text, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Goal(Base):
    """A measurable target: proposed by the Team Lead, accepted by the owner, measured by code. RLS: tenant."""

    __tablename__ = "goals"

    goal_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.tenant_id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(Text)
    metric: Mapped[str] = mapped_column(Text)
    baseline: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    target: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    current: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    due: Mapped[date] = mapped_column(Date)
    why: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(Text, server_default="proposed")
    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("daily_reports.report_id", ondelete="RESTRICT"))
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
