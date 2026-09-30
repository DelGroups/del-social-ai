"""The community manager on its own: new comments get reply drafts, and in automatic mode the safe ones are sent.

The owner picks the mode on the Comments page (Settings.reply_mode):
- manual: nothing happens by itself; a person asks for drafts and sends them.
- approval: comments are checked every few minutes and new ones get drafts at once; a person sends them.
- auto: comments are checked every minute, day and night, and code sends a draft as soon as it passes
  every check below. A draft that fails one waits for a person, with the reason (hold) shown next to it.
YouTube has no push for new comments, so "at once" means the next check (worker.reply_round).

The checks are code, not the model (CLAUDE.md principle 2): the agent asked for no look, the reply is in
the comment's script (a Portuguese comment is not answered in Cyrillic or Arabic letters), it has no
link, phone or e-mail, the comment is at most a week old, and at most DAY_LIMIT automatic replies a day.
Credits: 1 per 20 comments answered automatically, counted across rounds; without credits nothing happens.
"""
import asyncio
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.billing.credits import CreditError
from del_social.connections.youtube import YouTubeClient, YouTubeError
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.llm import LLM
from del_social.models import YtReply
from del_social.youtube import comments
from del_social.youtube.channel import Studio

log = logging.getLogger(__name__)

DAY_LIMIT = 50  # automatic replies per channel in 24 hours (50 API units each)
MAX_AGE = timedelta(days=7)  # older comments are answered by a person
_CONTACT = re.compile(r"https?://|www\.|\b[\w.-]+\.(com|net|org|az|ru|io|me|ly|be)\b|@\w+\.\w+|\+?\d[\d\s()-]{7,}\d", re.I)


_locks: dict[uuid.UUID, asyncio.Lock] = {}  # one round per channel at a time (the minute loop and the Check button)


@dataclass
class Result:
    drafted: int = 0
    sent: int = 0
    held: int = 0


def hold_reason(r: YtReply, now: datetime, sent_today: int) -> str | None:
    """Why this draft may not go out by itself, or None when it may."""
    if r.hold in ("check", "language"):
        return r.hold
    if _CONTACT.search(r.draft):
        return "link"
    if r.published_at is None or now - r.published_at > MAX_AGE:
        return "old"
    if sent_today >= DAY_LIMIT:
        return "limit"
    return None


async def run(engine: AsyncEngine, llm: LLM | None, yt: YouTubeClient, vault: TokenVault, studio: Studio,
              now: datetime | None = None) -> Result:
    """Call after comments.fetch. Does nothing in manual mode or without a model."""
    now = now or datetime.now(UTC)
    out = Result()
    mode = studio.settings.reply_mode
    if mode == "manual" or llm is None:
        return out
    lock = _locks.setdefault(studio.connection_id, asyncio.Lock())
    async with lock:
        return await _round(engine, llm, yt, vault, studio, now, mode, out)


async def _round(engine: AsyncEngine, llm: LLM, yt: YouTubeClient, vault: TokenVault, studio: Studio, now: datetime, mode: str,
                 out: Result) -> Result:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        # only recent comments are answered by themselves; older ones stay for a person (no credits spent on them)
        ids = list((await db.scalars(select(YtReply.reply_id).where(
            YtReply.connection_id == studio.connection_id, YtReply.status == "new", YtReply.published_at >= now - MAX_AGE)
            .order_by(YtReply.published_at.desc()).limit(comments.BATCH))).all())
    if ids:
        try:
            out.drafted = await comments.draft(engine, llm, studio, ids, None, auto=True)
        except CreditError as e:
            log.info("no automatic reply drafts for %s: %s", studio.tenant_id, e)
            return out
    if mode != "auto" or not ids:
        return out
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        rows = list((await db.scalars(select(YtReply).where(YtReply.reply_id.in_(ids), YtReply.status == "drafted")
                                      .order_by(YtReply.published_at.asc().nullsfirst()))).all())
        sent_today = await db.scalar(select(func.count()).where(
            YtReply.connection_id == studio.connection_id, YtReply.sent_by == "agent", YtReply.sent_at >= now - timedelta(days=1))) or 0
    for r in rows:
        reason = hold_reason(r, now, sent_today + out.sent)
        if reason:
            await _hold(engine, studio.tenant_id, r.reply_id, reason)
            out.held += 1
            continue
        try:
            await comments.send(engine, yt, vault, studio.tenant_id, r.reply_id, r.draft, by="agent")
            out.sent += 1
        except YouTubeError as e:
            if e.auth:
                raise
            log.warning("automatic reply for %s failed: %s", r.comment_id, e)
            await _hold(engine, studio.tenant_id, r.reply_id, "error")
            out.held += 1
    return out


async def _hold(engine: AsyncEngine, tenant_id: uuid.UUID, reply_id: uuid.UUID, reason: str) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        (await db.get(YtReply, reply_id)).hold = reason
