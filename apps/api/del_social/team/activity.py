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
AGENTS = ("team_lead", "media_analyst", "copywriter", "brand_guardian", "visual_editor", "publisher")

POST_STEPS = [
    {"key": "photos", "agent": "media_analyst"},
    {"key": "copy", "agent": "copywriter"},
    {"key": "guard", "agent": "brand_guardian"},
    {"key": "approval", "agent": None},
    {"key": "publish", "agent": "publisher"},
]


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
        task = await db.get(Task, task_id)
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
