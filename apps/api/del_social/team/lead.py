"""Running the Team Lead: build its view of the company, get its decision, execute the actions.

The Team Lead only chooses from a fixed menu of actions; this module checks each one
(ids exist in this tenant, the person may do it, times are computed by code) and starts it.
"""
import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents import team_lead
from del_social.billing import quota
from del_social.core.db import set_tenant
from del_social.llm import LLM, LLMError
from del_social.media import analysis
from del_social.media.storage import MediaStore
from del_social.models import AgentEvent, ChatMessage, MediaAsset, Post, Product, Task
from del_social.posts import service
from del_social.team import activity, timing, work

log = logging.getLogger(__name__)

HISTORY = 14
_running: set[asyncio.Task] = set()  # keeps background work alive; tests await it


def spawn(fn: Any, **kwargs: Any) -> None:
    task = asyncio.create_task(fn(**kwargs))
    _running.add(task)
    task.add_done_callback(_running.discard)


async def settle() -> None:
    """Wait for all work started from the chat (used by tests and on shutdown)."""
    while _running:
        await asyncio.gather(*list(_running), return_exceptions=True)


async def _context(db: AsyncSession, now: datetime) -> str:
    products = (await db.scalars(select(Product).where(Product.deleted_at.is_(None)).order_by(Product.name))).all()
    product_rows = []
    for p in products:
        photos = (await db.scalars(
            select(MediaAsset).where(MediaAsset.product_id == p.product_id, MediaAsset.deleted_at.is_(None))
        )).all()
        product_rows.append({
            "product_id": str(p.product_id), "name": p.name, "category": p.category,
            "publishable_photos": sum(service.publishable(m) for m in photos),
        })
    posts = (await db.scalars(select(Post).where(Post.status != "archived").order_by(Post.created_at.desc()).limit(10))).all()
    names = {p.product_id: p.name for p in products}
    post_rows = [{
        "post_id": str(p.post_id), "product": names.get(p.product_id), "status": p.status,
        "scheduled_baku": timing.baku_label(p.scheduled_at) or None,
        "published_baku": timing.baku_label(p.published_at) or None,
        "caption_start": (p.caption or "")[:120], "links": {c: r.get("url") for c, r in (p.results or {}).items() if r.get("url")},
    } for p in posts]
    tasks = (await db.scalars(select(Task).order_by(Task.created_at.desc()).limit(8))).all()
    task_rows = [{"title": t.title, "status": t.status, "steps": {s["key"]: s["status"] for s in t.steps}} for t in tasks]
    events = (await db.scalars(select(AgentEvent).order_by(AgentEvent.created_at.desc()).limit(12))).all()
    event_rows = [f"{timing.baku_label(e.created_at)} {e.agent} {e.kind}: {e.title}" for e in reversed(events)]
    unanalysed = await db.scalar(select(func.count()).where(
        MediaAsset.kind == "photo", MediaAsset.deleted_at.is_(None), MediaAsset.analyzed_at.is_(None),
        MediaAsset.parent_asset_id.is_(None),
    ))
    history = (await db.scalars(select(ChatMessage).order_by(ChatMessage.created_at.desc()).limit(HISTORY))).all()
    convo = [
        f"{'OWNER' if m.role == 'user' else (m.agent or 'agent').upper()}: {m.text}" for m in reversed(history)
    ]
    baku_now = now.astimezone(timing.BAKU)
    return "\n\n".join([
        f"<now>{baku_now.strftime('%A %Y-%m-%d %H:%M')} Baku time</now>",
        "<products>\n" + json.dumps(product_rows, ensure_ascii=False, indent=1) + "\n</products>",
        f"<photos_without_analysis>{unanalysed}</photos_without_analysis>",
        "<posts>\n" + json.dumps(post_rows, ensure_ascii=False, indent=1) + "\n</posts>",
        "<tasks>\n" + json.dumps(task_rows, ensure_ascii=False, indent=1) + "\n</tasks>",
        "<activity>\n" + "\n".join(event_rows) + "\n</activity>",
        "<conversation>\nThe last message is the one to answer.\n" + "\n".join(convo) + "\n</conversation>",
    ])


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


async def run_lead(
    *, engine: AsyncEngine, llm: LLM, store: MediaStore, tenant_id: uuid.UUID, account_id: uuid.UUID, can_act: bool,
) -> None:
    await activity.event(engine, tenant_id, "team_lead", "started", "Mesajı oxuyur")
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            context = await _context(db, datetime.now(UTC))
        decision = (await team_lead.decide(llm, tenant_id, context)).output
    except LLMError as e:
        await activity.event(engine, tenant_id, "team_lead", "failed", f"Cavab verə bilmədi: {e}")
        await activity.say(engine, tenant_id, "team_lead", f"Hazırda cavab verə bilmirəm ({e}). Bir az sonra yenidən yazın.")
        return

    notes: list[str] = []
    started = 0
    for action in decision.actions[:3]:
        if not can_act:
            notes.append("Sizin rolunuz tapşırıq verməyə icazə vermir; yalnız sual verə bilərsiniz.")
            break
        try:
            if action.type == "create_post":
                when = action.when or "after_approval"
                scheduled = timing.resolve(when, action.day, action.time)
                async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
                    await set_tenant(db, tenant_id)
                    await work.start_post(
                        db=db, engine=engine, llm=llm, schedule=spawn, tenant_id=tenant_id, account_id=account_id,
                        product_id=_uuid(action.product_id) or uuid.UUID(int=0), fmt=action.format,
                        channels=list(action.channels or ["instagram", "facebook"]), notes=action.notes or "",
                        scheduled_at=scheduled,
                    )
                started += 1
            elif action.type == "revise_post":
                post_id = _uuid(action.post_id)
                async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
                    await set_tenant(db, tenant_id)
                    post = await db.get(Post, post_id) if post_id else None
                if post is None or post.status != "ready" or not action.instruction:
                    raise work.WorkError("That post can't be changed now")
                spawn(service.revise, engine=engine, llm=llm, tenant_id=tenant_id, post_id=post_id,
                      instruction=action.instruction)
                started += 1
            elif action.type == "analyze_photos":
                async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
                    await set_tenant(db, tenant_id)
                    ids = (await db.scalars(select(MediaAsset.asset_id).where(
                        MediaAsset.kind == "photo", MediaAsset.status == "ready", MediaAsset.deleted_at.is_(None),
                        MediaAsset.analyzed_at.is_(None), MediaAsset.parent_asset_id.is_(None),
                    ))).all()
                for asset_id in ids:
                    spawn(analysis.run_analysis, engine=engine, llm=llm, store=store, tenant_id=tenant_id, asset_id=asset_id)
                started += 1
        except (work.WorkError, timing.TimingError, quota.QuotaError) as e:
            notes.append(f"Alınmadı: {e}.")
    reply = decision.reply.strip() + ("\n\n" + " ".join(notes) if notes else "")
    await activity.say(engine, tenant_id, "team_lead", reply)
    await activity.event(engine, tenant_id, "team_lead", "finished",
                         f"{started} tapşırıq başladıldı" if started else "Cavab verdi")


def since(minutes: int) -> datetime:
    return datetime.now(UTC) - timedelta(minutes=minutes)
