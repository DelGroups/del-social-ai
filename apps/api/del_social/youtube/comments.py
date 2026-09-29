"""Comments under the channel's videos: fetched, reply drafts written, sent only when the owner approves.

Comments are other people's words: the drafting agent reads them as data and holds no tools; sending
is a separate, explicit action by a person (CLAUDE.md principles 5 and 6).
"""
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
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


def _ts(v: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((v or "").replace("Z", "+00:00"))
    except ValueError:
        return None


async def fetch(engine: AsyncEngine, yt: YouTubeClient, vault: TokenVault, studio: Studio) -> int:
    """New top-level comments without a reply from the channel. Returns how many were added."""
    threads = await yt.comment_threads(creds(vault, studio), channel_id=studio.connection.external_id, limit=100)
    added = 0
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        for t in threads:
            sn = t.get("snippet") or {}
            top = ((sn.get("topLevelComment") or {}).get("snippet")) or {}
            if top.get("authorChannelId", {}).get("value") == studio.connection.external_id:
                continue  # the channel's own comment
            if sn.get("totalReplyCount", 0) and sn.get("canReply") is False:
                continue
            res = await db.execute(insert(YtReply).values(
                tenant_id=studio.tenant_id, connection_id=studio.connection_id, comment_id=t["id"],
                video_id=sn.get("videoId"), author=(top.get("authorDisplayName") or "")[:100],
                text=(top.get("textDisplay") or top.get("textOriginal") or "")[:2000], published_at=_ts(top.get("publishedAt")),
            ).on_conflict_do_nothing(constraint="uq_yt_replies_comment"))
            added += res.rowcount or 0
    return added


async def draft(engine: AsyncEngine, llm: LLM, studio: Studio, ids: list[uuid.UUID], by: uuid.UUID | None) -> int:
    """Reply drafts for up to 20 comments (1 credit). Returns how many drafts were written."""
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        rows = list((await db.scalars(select(YtReply).where(YtReply.reply_id.in_(ids[:BATCH]), YtReply.status.in_(("new", "drafted"))))).all())
        rows.sort(key=lambda r: ids.index(r.reply_id))  # the order the person listed them
        if not rows:
            return 0
        titles = {v.video_id: v.title for v in (await db.scalars(select(YtVideo).where(
            YtVideo.video_id.in_([r.video_id for r in rows if r.video_id])))).all()}
        ref = uuid.uuid4()
        await credits.spend(db, studio.tenant_id, credits.COST["comments"], "comments", ref, by)
    listing: list[dict[str, Any]] = [{"index": i, "video": titles.get(r.video_id or "", ""), "comment": r.text} for i, r in enumerate(rows)]
    text = (f"<channel>\n{reports.dumps(studio.channel_block())}\n</channel>\n"
            f"<comments>\n{reports.dumps(listing)}\n</comments>")
    try:
        out = (await agents.replies(llm, studio.tenant_id, text)).output
    except Exception:
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, studio.tenant_id)
            await credits.refund(db, studio.tenant_id, ref)
        raise
    written = 0
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        for d in out.replies:
            if 0 <= d.index < len(rows):
                r = await db.get(YtReply, rows[d.index].reply_id)
                if d.skip or not d.reply.strip():
                    r.status, r.draft = "dismissed", ""
                else:
                    r.status, r.draft = "drafted", d.reply.strip()[:1500]
                    written += 1
    return written


async def send(engine: AsyncEngine, yt: YouTubeClient, vault: TokenVault, tenant_id: uuid.UUID, reply_id: uuid.UUID, text: str) -> None:
    """The owner approved this reply: post it under the comment."""
    studio = await load(engine, tenant_id)
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        row = await db.get(YtReply, reply_id)
    await yt.reply(creds(vault, studio), row.comment_id, text.strip())
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        r = await db.get(YtReply, reply_id)
        r.status, r.draft, r.sent_at = "sent", text.strip(), datetime.now(UTC)
