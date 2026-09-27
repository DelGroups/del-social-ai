"""The Team Room: chat with the Team Lead and the live view of the team (ADR-less, plan §13 A)."""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.core.db import set_tenant
from del_social.core.deps import TenantContext, get_db, get_engine, require_permission
from del_social.llm import LLM
from del_social.media.storage import MediaStore
from del_social.models import AgentEvent, ChatMessage, Connection, MediaAsset, Post, Task
from del_social.routes.media import _current_logo, get_analyst, get_store
from del_social.routes.posts import PostOut, _out as post_out
from del_social.team import activity, lead, timing
from del_social.tenants.permissions import Permission, has_permission

router = APIRouter(prefix="/tenants/{tenant_id}/team", tags=["team"])

can_view = require_permission(Permission.VIEW)

WORKING_WINDOW = timedelta(minutes=10)
JOB_LINGER = timedelta(minutes=30)  # finished work stays on the live line this long


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class TaskOut(BaseModel):
    task_id: uuid.UUID
    title: str
    status: str
    steps: list[dict[str, Any]]
    post_id: uuid.UUID | None
    created_at: datetime


class MessageOut(BaseModel):
    message_id: uuid.UUID
    role: str
    agent: str | None
    text: str
    created_at: datetime
    task: TaskOut | None
    post: PostOut | None  # an approval / result card
    payload: dict[str, Any] | None  # a report card: {"type": "briefing" | "market", ...}


def _task(t: Task | None) -> TaskOut | None:
    return TaskOut.model_validate(t, from_attributes=True) if t else None


@router.get("/chat", response_model=list[MessageOut])
async def chat(
    limit: int = Query(default=60, ge=1, le=200),
    ctx: TenantContext = Depends(can_view),
    db: AsyncSession = Depends(get_db),
) -> list[MessageOut]:
    msgs = list(reversed((await db.scalars(
        select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(limit)
    )).all()))
    has_logo = await _current_logo(db) is not None
    tasks = {t.task_id: t for t in (await db.scalars(
        select(Task).where(Task.task_id.in_([m.task_id for m in msgs if m.task_id]))
    )).all()}
    posts = {p.post_id: p for p in (await db.scalars(
        select(Post).where(Post.post_id.in_([m.post_id for m in msgs if m.post_id]))
    )).all()}
    # Show a task card once, on its latest message; show a post card on every message that carries one
    last_for_task = {m.task_id: m.message_id for m in msgs if m.task_id}
    return [
        MessageOut(
            message_id=m.message_id, role=m.role, agent=m.agent, text=m.text, created_at=m.created_at,
            task=_task(tasks.get(m.task_id)) if m.task_id and last_for_task[m.task_id] == m.message_id else None,
            post=post_out(posts[m.post_id], has_logo) if m.post_id in posts else None,
            payload=m.payload,
        )
        for m in msgs
    ]


@router.post("/chat", status_code=status.HTTP_202_ACCEPTED)
async def send(
    body: ChatIn,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(can_view),
    engine: AsyncEngine = Depends(get_engine),
    llm: LLM | None = Depends(get_analyst),
    store: MediaStore = Depends(get_store),
) -> dict[str, str]:
    """Write to the Team Lead. It answers in the chat and starts work in the background."""
    async with AsyncSession(engine) as own, own.begin():
        await set_tenant(own, ctx.tenant_id)
        own.add(ChatMessage(tenant_id=ctx.tenant_id, role="user", text=body.text.strip(), author=ctx.account.account_id))
    if llm is None:
        await activity.say(engine, ctx.tenant_id, "team_lead", "Komanda hələ qurulmayıb (AI açarı yoxdur).")
        return {"status": "not_configured"}
    background.add_task(
        lead.run_lead, engine=engine, llm=llm, store=store, tenant_id=ctx.tenant_id,
        account_id=ctx.account.account_id, can_act=has_permission(ctx.role, Permission.APPROVE_CONTENT),
    )
    return {"status": "accepted"}


class AgentState(BaseModel):
    agent: str
    state: str  # working | idle
    activity: str | None
    last_at: datetime | None
    done_today: int


class Job(TaskOut):
    """A task on the live production line, with its first photo."""

    thumb_url: str | None
    post_status: str | None
    scheduled_at: datetime | None
    updated_at: datetime


class Live(BaseModel):
    agents: list[AgentState]
    running: list[TaskOut]
    jobs: list[Job]  # in progress, waiting, scheduled, and just finished (they leave the line after a while)
    waiting: list[PostOut]  # waiting for your approval
    scheduled: list[PostOut]
    published: list[PostOut]  # latest published
    events: list[dict[str, Any]]
    photos_total: int
    photos_unanalysed: int
    connections: list[dict[str, Any]]
    now: datetime


@router.get("/live", response_model=Live)
async def live(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> Live:
    now = datetime.now(UTC)
    has_logo = await _current_logo(db) is not None
    today = now.astimezone(timing.BAKU).replace(hour=0, minute=0, second=0, microsecond=0)

    agents = []
    for key in activity.AGENTS:
        last = await db.scalar(select(AgentEvent).where(AgentEvent.agent == key).order_by(AgentEvent.created_at.desc()).limit(1))
        done = await db.scalar(select(func.count()).where(
            AgentEvent.agent == key, AgentEvent.kind == "finished", AgentEvent.created_at >= today
        ))
        working = bool(last and last.kind == "started" and now - last.created_at < WORKING_WINDOW)
        agents.append(AgentState(
            agent=key, state="working" if working else "idle", activity=last.title if last else None,
            last_at=last.created_at if last else None, done_today=done or 0,
        ))

    def posts(*statuses: str, order=Post.created_at.desc(), limit=10):
        return select(Post).where(Post.status.in_(statuses)).order_by(order).limit(limit)

    running = (await db.scalars(select(Task).where(Task.status == "running").order_by(Task.created_at.desc()).limit(10))).all()
    waiting = (await db.scalars(posts("ready"))).all()
    scheduled = (await db.scalars(posts("scheduled", order=Post.scheduled_at))).all()
    published = (await db.scalars(posts("published", "partly_published", order=Post.published_at.desc(), limit=5))).all()
    job_rows = (await db.scalars(
        select(Task).where(or_(
            Task.status.in_(("running", "waiting_approval", "scheduled")),
            Task.updated_at >= now - JOB_LINGER,
        )).order_by(Task.created_at.desc()).limit(12)
    )).all()
    job_posts = {p.post_id: post_out(p, has_logo) for p in (await db.scalars(
        select(Post).where(Post.post_id.in_([t.post_id for t in job_rows if t.post_id]))
    )).all()}

    def job(t: Task) -> Job:
        p = job_posts.get(t.post_id) if t.post_id else None
        return Job(
            **TaskOut.model_validate(t, from_attributes=True).model_dump(), updated_at=t.updated_at,
            thumb_url=p.photos[0].url if p and p.photos else None, post_status=p.status if p else None,
            scheduled_at=p.scheduled_at if p else None,
        )

    events = (await db.scalars(select(AgentEvent).order_by(AgentEvent.created_at.desc()).limit(30))).all()

    photos_total = await db.scalar(select(func.count()).where(MediaAsset.kind == "photo", MediaAsset.deleted_at.is_(None)))
    unanalysed = await db.scalar(select(func.count()).where(
        MediaAsset.kind == "photo", MediaAsset.deleted_at.is_(None), MediaAsset.analyzed_at.is_(None),
        MediaAsset.parent_asset_id.is_(None),
    ))
    conns = (await db.scalars(select(Connection).order_by(Connection.created_at))).all()
    return Live(
        agents=agents,
        running=[TaskOut.model_validate(t, from_attributes=True) for t in running],
        jobs=[job(t) for t in reversed(job_rows)],
        waiting=[post_out(p, has_logo) for p in waiting],
        scheduled=[post_out(p, has_logo) for p in scheduled],
        published=[post_out(p, has_logo) for p in published],
        events=[{"agent": e.agent, "kind": e.kind, "title": e.title, "at": e.created_at} for e in events],
        photos_total=photos_total or 0, photos_unanalysed=unanalysed or 0,
        connections=[{"channel": c.channel, "name": c.display_name, "status": c.status} for c in conns],
        now=now,
    )
