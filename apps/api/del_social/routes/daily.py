"""Daily reports (market research, the Team Lead's morning report) and acting on suggestions (ADR 008)."""
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.billing import quota
from del_social.connections.meta import MetaClient
from del_social.core.db import set_tenant
from del_social.core.deps import TenantContext, get_db, get_engine, get_http, get_meta_optional, get_vault_optional, require_permission
from del_social.core.vault import TokenVault
from del_social.llm import LLM
from del_social.models import ChatMessage, DailyReport
from del_social.routes.media import get_analyst
from del_social.team import daily, lead, meeting, timing, work
from del_social.tenants.permissions import Permission

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["daily"])

can_view = require_permission(Permission.VIEW)
can_run = require_permission(Permission.MANAGE_BRAND)  # owners and admins: it costs AI credit
can_act = require_permission(Permission.APPROVE_CONTENT)


class ReportRow(BaseModel):
    report_id: uuid.UUID
    kind: str
    day: date
    status: str
    headline: str | None
    error: str | None
    created_at: datetime
    finished_at: datetime | None


class ReportOut(ReportRow):
    input: dict[str, Any]
    output: dict[str, Any] | None
    sources: list[dict[str, Any]]


def _row(r: DailyReport) -> dict[str, Any]:
    out = r.output or {}
    return {
        "report_id": r.report_id, "kind": r.kind, "day": r.day, "status": r.status,
        "headline": out.get("headline") or out.get("greeting") or out.get("focus"), "error": r.error,
        "created_at": r.created_at, "finished_at": r.finished_at,
    }


@router.get("/daily", response_model=list[ReportRow])
async def list_reports(
    kind: Literal["market", "briefing", "meeting"] | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    ctx: TenantContext = Depends(can_view),
    db: AsyncSession = Depends(get_db),
) -> list[ReportRow]:
    q = select(DailyReport).order_by(DailyReport.day.desc(), DailyReport.kind).limit(limit)
    if kind:
        q = q.where(DailyReport.kind == kind)
    return [ReportRow(**_row(r)) for r in (await db.scalars(q)).all()]


@router.get("/daily/{report_id}", response_model=ReportOut)
async def get_report(report_id: uuid.UUID, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> ReportOut:
    r = await db.get(DailyReport, report_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Report not found")
    # Collected raw data is kept for the record; image links from Instagram's CDN are left out
    data = {k: v for k, v in (r.input or {}).items() if k != "collected_at"}
    return ReportOut(**_row(r), input=data, output=r.output, sources=r.sources or [])


@router.post("/daily/{kind}/run", response_model=ReportRow, status_code=status.HTTP_202_ACCEPTED)
async def run_now(
    kind: Literal["market", "briefing", "meeting"],
    ctx: TenantContext = Depends(can_run),
    db: AsyncSession = Depends(get_db),
    engine: AsyncEngine = Depends(get_engine),
    http: httpx.AsyncClient = Depends(get_http),
    llm: LLM | None = Depends(get_analyst),
    meta: MetaClient | None = Depends(get_meta_optional),
    vault: TokenVault | None = Depends(get_vault_optional),
) -> ReportRow:
    """Make today's report now (again). Runs in the background; the Team Room shows progress."""
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The agents are not configured on the server")
    a = await quota.allowance(db)
    if a.state in ("none", "expired"):
        raise quota.QuotaError("no_plan" if a.state == "none" else "expired", "An active package is needed for the team's daily work.")
    day = daily.baku_day(datetime.now(UTC))
    rid = await daily.claim(engine, ctx.tenant_id, kind, day, force=True)
    if rid is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This report is being made right now")
    if kind == "market":
        lead.spawn(daily.run_market, engine=engine, http=http, llm=llm, meta=meta, vault=vault, tenant_id=ctx.tenant_id, report_id=rid)
    elif kind == "briefing":
        lead.spawn(daily.run_briefing, engine=engine, llm=llm, tenant_id=ctx.tenant_id, report_id=rid)
    else:
        lead.spawn(meeting.run_meeting, engine=engine, llm=llm, tenant_id=ctx.tenant_id, report_id=rid)
    async with AsyncSession(engine) as own, own.begin():
        await set_tenant(own, ctx.tenant_id)
        return ReportRow(**_row(await own.get(DailyReport, rid)))


@router.post("/team/messages/{message_id}/suggestions/{index}/accept", status_code=status.HTTP_202_ACCEPTED)
async def accept_suggestion(
    message_id: uuid.UUID,
    index: int,
    ctx: TenantContext = Depends(can_act),
    db: AsyncSession = Depends(get_db),
    engine: AsyncEngine = Depends(get_engine),
    llm: LLM | None = Depends(get_analyst),
) -> dict[str, Any]:
    """The owner agrees with a suggestion from the morning report: the team starts that post."""
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The agents are not configured on the server")
    msg = await db.get(ChatMessage, message_id)
    payload = (msg.payload or {}) if msg else {}
    items = (payload.get("briefing") or {}).get("suggestions") or []
    if msg is None or payload.get("type") != "briefing" or not 0 <= index < len(items):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Suggestion not found")
    item = items[index]
    if item.get("status") != "open" or item.get("action") != "create_post" or not item.get("product_id"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This suggestion can't be started")
    try:
        when = timing.resolve(item.get("when") or "after_approval")
    except timing.TimingError:
        when = None
    try:
        post = await work.start_post(
            db=db, engine=engine, llm=llm, schedule=lead.spawn, tenant_id=ctx.tenant_id, account_id=ctx.account.account_id,
            product_id=uuid.UUID(item["product_id"]), notes=item.get("notes") or item.get("why") or "", scheduled_at=when,
        )
    except work.WorkError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    # Only the payload column may change (column grant): mark the suggestion as started
    items = [dict(x) for x in items]
    items[index] |= {"status": "started", "post_id": str(post.post_id), "task_id": str(post.task_id)}
    msg.payload = payload | {"briefing": (payload.get("briefing") or {}) | {"suggestions": items}}
    await db.flush()
    return {"status": "started", "post_id": str(post.post_id)}
