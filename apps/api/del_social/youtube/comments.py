"""Comments under the channel's videos: fetched, reply drafts written, and sent.

Comments are other people's words: the drafting agent reads them as data and holds no tools. Sending
is code: a person presses Send, or, in the owner's automatic mode, autoreply.py sends the drafts that
pass its checks (CLAUDE.md principles 5 and 6).
"""
import math
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents import youtube as agents
from del_social.billing import credits
from del_social.connections.youtube import YouTubeClient
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.llm import LLM
from del_social.models import YtReply, YtVideo
from del_social.youtube import reports
from del_social.youtube.channel import Studio, creds, load

BATCH = 20
_SCRIPTS = {"arabic": re.compile(r"[؀-ۿ]"), "cyrillic": re.compile(r"[Ѐ-ӿ]"),
            "cjk": re.compile(r"[぀-ヿ一-鿿가-힯]"), "latin": re.compile(r"[A-Za-zÀ-ɏ]")}


def script(text: str) -> str | None:
    """The writing system most of the text is in (None for emoji, numbers, links only)."""
    counts = {k: len(p.findall(re.sub(r"https?://\S+|@\S+", "", text or ""))) for k, p in _SCRIPTS.items()}
    best = max(counts, key=lambda k: counts[k])
    return best if counts[best] >= 2 else None


def same_language(comment: str, reply: str) -> bool:
    """Code's check that the reply is at least written in the comment's script (Russian → Cyrillic, Persian → Arabic…)."""
    c = script(comment)
    return c is None or script(reply) in (c, None)


def reply_context(studio: Studio) -> dict[str, Any]:
    """The channel as the replies agent sees it: no channel languages, a reply follows the commenter's language."""
    return {k: v for k, v in studio.channel_block().items() if k not in ("languages", "country")}


def _ts(v: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((v or "").replace("Z", "+00:00"))
    except ValueError:
        return None


async def fetch(engine: AsyncEngine, yt: YouTubeClient, vault: TokenVault, studio: Studio) -> int:
    """New top-level comments without a reply from the channel. Returns how many were added."""
    own = studio.connection.external_id
    threads = await yt.comment_threads(creds(vault, studio), channel_id=own, limit=100, replies=True)
    added = 0
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        for t in threads:
            sn = t.get("snippet") or {}
            top = ((sn.get("topLevelComment") or {}).get("snippet")) or {}
            if top.get("authorChannelId", {}).get("value") == own:
                continue  # the channel's own comment
            if sn.get("canReply") is False:
                continue
            answered = any(((c.get("snippet") or {}).get("authorChannelId") or {}).get("value") == own
                           for c in (t.get("replies") or {}).get("comments") or [])
            if answered:  # the creator already replied in YouTube itself: never answer twice
                row = await db.scalar(select(YtReply).where(YtReply.connection_id == studio.connection_id, YtReply.comment_id == t["id"]))
                if row is not None and row.status in ("new", "drafted"):
                    row.status = "dismissed"
                continue
            res = await db.execute(insert(YtReply).values(
                tenant_id=studio.tenant_id, connection_id=studio.connection_id, comment_id=t["id"],
                video_id=sn.get("videoId"), author=(top.get("authorDisplayName") or "")[:100],
                text=(top.get("textDisplay") or top.get("textOriginal") or "")[:2000], published_at=_ts(top.get("publishedAt")),
            ).on_conflict_do_nothing(constraint="uq_yt_replies_comment"))
            added += res.rowcount or 0
    return added


async def draft(engine: AsyncEngine, llm: LLM, studio: Studio, ids: list[uuid.UUID], by: uuid.UUID | None, auto: bool = False) -> int:
    """Reply drafts for up to 20 comments. Returns how many drafts were written.

    Asked by a person: 1 credit per call. Automatic (auto=True, one comment at a time as they arrive):
    1 credit per 20 comments, counted over all the channel's automatic drafts, so answering each comment
    at once costs the same as answering them in batches of 20."""
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        rows = list((await db.scalars(select(YtReply).where(YtReply.reply_id.in_(ids[:BATCH]), YtReply.status.in_(("new", "drafted"))))).all())
        rows.sort(key=lambda r: ids.index(r.reply_id))  # the order the person listed them
        if not rows:
            return 0
        titles = {v.video_id: v.title for v in (await db.scalars(select(YtVideo).where(
            YtVideo.video_id.in_([r.video_id for r in rows if r.video_id])))).all()}
        ref = uuid.uuid4()
        if auto:
            done = await db.scalar(select(func.count()).where(YtReply.connection_id == studio.connection_id, YtReply.drafted_by == "agent")) or 0
            cost = credits.COST["comments"] * (math.ceil((done + len(rows)) / BATCH) - math.ceil(done / BATCH))
            for r in rows:
                r.drafted_by = "agent"
        else:
            cost = credits.COST["comments"]
        if cost:
            await credits.spend(db, studio.tenant_id, cost, "comments", ref, by)
        else:
            await credits.require_addon(db)
    listing: list[dict[str, Any]] = [{"index": i, "comment": r.text, "video": titles.get(r.video_id or "", "")} for i, r in enumerate(rows)]
    text = (f"<channel>\n{reports.dumps(reply_context(studio))}\n</channel>\n"
            f"<comments>\n{reports.dumps(listing)}\n</comments>")
    try:
        out = (await agents.replies(llm, studio.tenant_id, text)).output
    except Exception:
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, studio.tenant_id)
            await credits.refund(db, studio.tenant_id, ref)
            for r in rows if auto else []:
                (await db.get(YtReply, r.reply_id)).drafted_by = None  # not paid for, not counted
        raise
    written = 0
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        for d in out.replies:
            if 0 <= d.index < len(rows):
                r = await db.get(YtReply, rows[d.index].reply_id)
                if d.skip or not d.reply.strip():
                    r.status, r.draft, r.hold = "dismissed", "", None
                else:
                    reply = d.reply.strip()[:1500]
                    hold = "check" if d.needs_owner else None if same_language(r.text, reply) else "language"
                    r.status, r.draft, r.hold = "drafted", reply, hold
                    written += 1
    return written


async def send(engine: AsyncEngine, yt: YouTubeClient, vault: TokenVault, tenant_id: uuid.UUID, reply_id: uuid.UUID, text: str,
               by: str = "person") -> None:
    """Post the reply under the comment: a person approved it, or (by="agent") it passed the automatic checks."""
    studio = await load(engine, tenant_id)
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        row = await db.get(YtReply, reply_id)
    await yt.reply(creds(vault, studio), row.comment_id, text.strip())
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        r = await db.get(YtReply, reply_id)
        r.status, r.draft, r.sent_at, r.sent_by, r.hold = "sent", text.strip(), datetime.now(UTC), by, None
