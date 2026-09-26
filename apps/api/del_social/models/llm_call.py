import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class LlmCall(Base):
    """One LLM request: who (tenant, agent), which prompt and model, tokens, cost, latency.

    RLS: tenant-scoped. Append-only for del_app (SELECT + INSERT). The prompt and output
    text live in Langfuse (trace_id), not here.
    """

    __tablename__ = "llm_calls"

    call_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT")
    )
    agent: Mapped[str] = mapped_column(Text)
    prompt_ref: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)  # ok | error
    input_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_read_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cache_write_tokens: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
