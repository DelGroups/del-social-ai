"""AI usage and cost of one tenant, per month and per agent (from llm_calls)."""
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.deps import TenantContext, get_db, require_permission
from del_social.models import LlmCall
from del_social.tenants.permissions import Permission

router = APIRouter(prefix="/tenants/{tenant_id}/usage", tags=["usage"])

can_view_usage = require_permission(Permission.VIEW_USAGE)


class AgentUsage(BaseModel):
    agent: str
    calls: int
    errors: int
    input_tokens: int
    output_tokens: int
    cost_usd: Decimal


class UsageOut(BaseModel):
    month: str  # YYYY-MM (UTC)
    calls: int
    cost_usd: Decimal
    by_agent: list[AgentUsage]


def _month_range(month: str | None) -> tuple[str, datetime, datetime]:
    now = datetime.now(UTC)
    try:
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC) if month else now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
    except ValueError:
        raise HTTPException(422, "month must be YYYY-MM") from None
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start.strftime("%Y-%m"), start, end


@router.get("", response_model=UsageOut)
async def usage(
    month: str | None = Query(default=None, max_length=7),
    ctx: TenantContext = Depends(can_view_usage),
    db: AsyncSession = Depends(get_db),
) -> UsageOut:
    label, start, end = _month_range(month)
    rows = (
        await db.execute(
            select(
                LlmCall.agent,
                func.count(),
                func.count().filter(LlmCall.status == "error"),
                func.coalesce(func.sum(LlmCall.input_tokens + LlmCall.cache_read_tokens + LlmCall.cache_write_tokens), 0),
                func.coalesce(func.sum(LlmCall.output_tokens), 0),
                func.coalesce(func.sum(LlmCall.cost_usd), 0),
            )
            .where(LlmCall.created_at >= start, LlmCall.created_at < end)
            .group_by(LlmCall.agent)
            .order_by(func.sum(LlmCall.cost_usd).desc().nulls_last())
        )
    ).all()
    by_agent = [
        AgentUsage(agent=a, calls=c, errors=e, input_tokens=i, output_tokens=o, cost_usd=Decimal(cost))
        for a, c, e, i, o, cost in rows
    ]
    return UsageOut(
        month=label,
        calls=sum(a.calls for a in by_agent),
        cost_usd=sum((a.cost_usd for a in by_agent), Decimal(0)),
        by_agent=by_agent,
    )
