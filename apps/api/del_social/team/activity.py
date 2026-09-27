"""Writing what the team does: live events, task steps, messages in the Team Room.

Every function opens its own short transaction, so background jobs can report progress
as it happens and the panel sees it immediately.
"""
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.core.db import set_tenant
from del_social.models import AgentEvent, ChatMessage, Task

# Agents shown in the Team Room (display names are translated in the panel)
AGENTS = ("team_lead", "market_researcher", "media_analyst", "copywriter", "brand_guardian", "visual_editor", "publisher")

POST_STEPS = [
    {"key": "photos", "agent": "media_analyst"},
    {"key": "copy", "agent": "copywriter"},
    {"key": "guard", "agent": "brand_guardian"},
    {"key": "approval", "agent": None},
    {"key": "publish", "agent": "publisher"},
]


# The Market Researcher's morning work, step by step (shown live as a workflow)
MARKET_STEPS = [
    {"key": "competitors", "agent": "market_researcher"},
    {"key": "own_page", "agent": "market_researcher"},
    {"key": "web", "agent": "market_researcher"},
    {"key": "analyse", "agent": "market_researcher"},
    {"key": "deliver", "agent": "market_researcher"},
]
# The Team Lead's morning report
BRIEFING_STEPS = [
    {"key": "facts", "agent": "team_lead"},
    {"key": "read_market", "agent": "team_lead"},
    {"key": "plan", "agent": "team_lead"},
    {"key": "deliver", "agent": "team_lead"},
]


async def new_task(engine: AsyncEngine, tenant_id: uuid.UUID, kind: str, title: str, steps: list[dict[str, Any]]) -> uuid.UUID:
    """A task whose steps the panel draws as a live workflow."""
    task_id = uuid.uuid4()
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        db.add(Task(task_id=task_id, tenant_id=tenant_id, title=title[:200], kind=kind, status="running",
                    steps=[{"key": s["key"], "agent": s["agent"], "status": "pending"} for s in steps]))
    return task_id


async def event(
    engine: AsyncEngine, tenant_id: uuid.UUID, agent: str, kind: str, title: str,
    task_id: uuid.UUID | None = None, post_id: uuid.UUID | None = None,
) -> None:
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        db.add(AgentEvent(tenant_id=tenant_id, agent=agent, kind=kind, title=title[:300], task_id=task_id, post_id=post_id))


async def say(
    engine: AsyncEngine, tenant_id: uuid.UUID, agent: str, text: str,
    task_id: uuid.UUID | None = None, post_id: uuid.UUID | None = None,
) -> None:
    """An agent writes in the Team Room (post_id makes the panel show an approval card)."""
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        db.add(ChatMessage(tenant_id=tenant_id, role="agent", agent=agent, text=text[:4000], task_id=task_id, post_id=post_id))


async def step(
    engine: AsyncEngine, tenant_id: uuid.UUID, task_id: uuid.UUID | None, key: str, status: str,
    task_status: str | None = None, note: str | None = None,
) -> None:
    """Move one wizard step (pending → running → done | waiting | failed)."""
    if task_id is None:
        return
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        # Locked: steps of one task can finish at the same moment (a meeting's members answer in parallel)
        task = await db.get(Task, task_id, with_for_update=True)
        if task is None:
            return
        steps: list[dict[str, Any]] = [dict(s) for s in task.steps]
        for s in steps:
            if s["key"] == key:
                s["status"] = status
                if note is not None:
                    s["note"] = note[:200]
        task.steps = steps
        if task_status:
            task.status = task_status
