"""Goals, the week plan from a meeting, and the competitors the team watches (ADR 009)."""
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.billing import quota
from del_social.core.deps import TenantContext, get_db, get_engine, require_permission
from del_social.llm import LLM
from del_social.models import ChatMessage, Competitor, Goal
from del_social.routes.media import get_analyst
from del_social.team import lead, meeting, metrics, timing, work
from del_social.tenants.permissions import Permission

router = APIRouter(prefix="/tenants/{tenant_id}", tags=["strategy"])

can_view = require_permission(Permission.VIEW)
can_act = require_permission(Permission.APPROVE_CONTENT)
can_decide = require_permission(Permission.MANAGE_BRAND)  # goals and competitors: owners and admins


@router.get("/goals")
async def list_goals(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(Goal).where(Goal.status != "dropped").order_by(Goal.created_at.desc()).limit(30))).all()
    return [metrics.goal_row(g) for g in rows]


class Decision(BaseModel):
    accept: bool


@router.post("/goals/{goal_id}/decision")
async def decide_goal(goal_id: uuid.UUID, body: Decision, ctx: TenantContext = Depends(can_decide),
                      db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    """The owner accepts a proposed goal (the team then works toward it) or declines it."""
    g = await db.get(Goal, goal_id)
    if g is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Goal not found")
    if g.status != "proposed":
        raise HTTPException(status.HTTP_409_CONFLICT, "This goal was already decided")
    if body.accept:
        now = (await metrics.current(db)).get(g.metric)
        if now is not None:
            g.baseline = g.current = now  # the starting point is the day it was accepted
    g.status = "active" if body.accept else "dropped"
    g.decided_by, g.decided_at = ctx.account.account_id, datetime.now(UTC)
    await db.flush()
    return metrics.goal_row(g)


@router.post("/team/messages/{message_id}/plan/accept", status_code=status.HTTP_202_ACCEPTED)
async def accept_plan(
    message_id: uuid.UUID,
    ctx: TenantContext = Depends(can_act),
    db: AsyncSession = Depends(get_db),
    engine: AsyncEngine = Depends(get_engine),
    llm: LLM | None = Depends(get_analyst),
) -> dict[str, Any]:
    """The owner approves the week plan: the team prepares each post, scheduled for its day. Each post
    still comes back for approval before it is published."""
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The agents are not configured on the server")
    msg = await db.get(ChatMessage, message_id)
    payload = (msg.payload or {}) if msg else {}
    if msg is None or payload.get("type") != "meeting":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Plan not found")
    plan = [dict(i) for i in payload.get("week_plan") or []]
    started, stopped = 0, None
    now = datetime.now(UTC)
    for item in plan:
        if item.get("status") != "open":
            continue
        at = datetime.combine(date.fromisoformat(item["date"]), meeting.PLAN_HOUR, timing.BAKU)
        if at <= now:
            item["status"] = "skipped"
            continue
        try:
            post = await work.start_post(
                db=db, engine=engine, llm=llm, schedule=lead.spawn, tenant_id=ctx.tenant_id, account_id=ctx.account.account_id,
                product_id=uuid.UUID(item["product_id"]), scheduled_at=at,
                notes=f"{item.get('angle', '')}. Format idea: {item.get('format', '')}. Why: {item.get('why', '')}"[:1000],
            )
        except (work.WorkError, quota.QuotaError) as e:
            stopped = str(e)
            break
        item |= {"status": "started", "post_id": str(post.post_id)}
        started += 1
    msg.payload = payload | {"week_plan": plan}
    await db.flush()
    if started == 0 and stopped:
        raise HTTPException(status.HTTP_409_CONFLICT, stopped)
    return {"started": started, "stopped": stopped}


@router.get("/competitors")
async def list_competitors(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    rows = (await db.scalars(select(Competitor).order_by(Competitor.status, Competitor.followers.desc().nulls_last()))).all()
    return [{
        "competitor_id": str(c.competitor_id), "username": c.username, "name": c.name, "source": c.source, "status": c.status,
        "followers": c.followers, "last_post_at": c.last_post_at.isoformat() if c.last_post_at else None,
        "checked_at": c.checked_at.isoformat() if c.checked_at else None, "note": c.note,
    } for c in rows]


class CompetitorPatch(BaseModel):
    status: Literal["ignored", "active"]


@router.patch("/competitors/{competitor_id}")
async def update_competitor(competitor_id: uuid.UUID, body: CompetitorPatch, ctx: TenantContext = Depends(can_decide),
                            db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    """Stop watching an account (or watch it again; the next research re-checks it)."""
    c = await db.get(Competitor, competitor_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Competitor not found")
    c.status = body.status
    await db.flush()
    return {"status": c.status}


def with_goals(payload: dict[str, Any] | None, goals: dict[str, Goal]) -> dict[str, Any] | None:
    """A meeting card shows its goals as they are now (accepted, declined, progress)."""
    if not payload or payload.get("type") != "meeting":
        return payload
    return payload | {"goals": [metrics.goal_row(goals[g]) for g in payload.get("goal_ids", []) if g in goals]}
