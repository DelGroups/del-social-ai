import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class EvalRun(Base):
    """One run of an agent eval suite over a set of briefs (docs/phase-1-plan.md §10). RLS: tenant."""

    __tablename__ = "eval_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.tenant_id", ondelete="RESTRICT"))
    suite: Mapped[str] = mapped_column(Text)  # e.g. "copywriter"
    status: Mapped[str] = mapped_column(Text, server_default="running")  # running | done | failed
    prompt_refs: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    brand_version: Mapped[int] = mapped_column(Integer)
    briefs_total: Mapped[int] = mapped_column(Integer)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvalItem(Base):
    """One brief's result in a run, plus the human rating of each option. RLS: tenant."""

    __tablename__ = "eval_items"

    item_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("eval_runs.run_id", ondelete="RESTRICT"), index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.tenant_id", ondelete="RESTRICT"))
    position: Mapped[int] = mapped_column(Integer)
    brief: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB)  # pipeline output; None while running or on error
    error: Mapped[str | None] = mapped_column(Text)
    ratings: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))  # {"0": "publishable", ...}
    note: Mapped[str | None] = mapped_column(Text)
    rated_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    rated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
