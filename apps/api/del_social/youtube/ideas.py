"""Video ideas from evidence: YouTube's popular chart, competitor outliers, web research.

Code gathers and scores the evidence (an outlier is a video with many times its channel's usual
views); the model turns it into ideas that point back to it. Competitor channels are added by
handle, link or id and checked on YouTube by code.
"""
import re
import uuid
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents import youtube as agents
from del_social.connections.base import Credentials
from del_social.connections.youtube import YouTubeClient
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.llm import LLM
from del_social.models import YtCompetitor, YtIdea
from del_social.youtube import numbers, reports, sync
from del_social.youtube.channel import Studio, creds, load, report_language

MAX_COMPETITORS = 15
_CHANNEL_ID = re.compile(r"(UC[\w-]{22})")
_HANDLE = re.compile(r"@([\w.\-]{3,30})")


def parse_channel(entry: str) -> tuple[str, str] | None:
    """'@autobaku', 'youtube.com/@autobaku', 'youtube.com/channel/UC…', 'UC…' → ("handle"|"id", value)."""
    s = entry.strip()
    if m := _CHANNEL_ID.search(s):
        return "id", m.group(1)
    if m := _HANDLE.search(s):
        return "handle", m.group(1)
    if re.fullmatch(r"[\w.\-]{3,30}", s):
        return "handle", s
    return None


def _age_days(published: str | None, now: datetime) -> int | None:
    try:
        return max(0, (now - datetime.fromisoformat((published or "").replace("Z", "+00:00"))).days)
    except ValueError:
        return None


async def add_competitors(engine: AsyncEngine, yt: YouTubeClient, vault: TokenVault, studio: Studio,
                          entries: list[str], source: str = "owner") -> tuple[list[str], list[str]]:
    """Look each channel up on YouTube and watch it. Returns (added titles, not found entries)."""
    c = creds(vault, studio)
    added, missing = [], []
    for entry in entries[:MAX_COMPETITORS]:
        parsed = parse_channel(entry)
        items = []
        if parsed:
            kind, value = parsed
            items = await yt.channels(c, ids=[value]) if kind == "id" else await yt.channels(c, handle=value)
        if not items or items[0]["id"] == studio.connection.external_id:
            missing.append(entry)
            continue
        await _save(engine, studio, items[0], source)
        added.append(items[0]["snippet"].get("title") or items[0]["id"])
    return added, missing


async def _save(engine: AsyncEngine, studio: Studio, ch: dict[str, Any], source: str) -> None:
    sn, st = ch.get("snippet") or {}, ch.get("statistics") or {}
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        row = await db.scalar(select(YtCompetitor).where(YtCompetitor.connection_id == studio.connection_id,
                                                         YtCompetitor.channel_id == ch["id"]))
        if row is None:
            row = YtCompetitor(competitor_id=uuid.uuid4(), tenant_id=studio.tenant_id, connection_id=studio.connection_id,
                               channel_id=ch["id"], source=source)
            db.add(row)
        row.handle, row.title = sn.get("customUrl"), sn.get("title") or ch["id"]
        row.avatar = ((sn.get("thumbnails") or {}).get("default") or {}).get("url")
        row.subscribers = None if st.get("hiddenSubscriberCount") else sync._int(st.get("subscriberCount"))
        row.videos, row.views = sync._int(st.get("videoCount")), sync._int(st.get("viewCount"))
        row.checked_at = datetime.now(UTC)


async def competitor_evidence(yt: YouTubeClient, c: Credentials, rivals: list[YtCompetitor], now: datetime) -> list[dict[str, Any]]:
    """Each watched channel's recent videos with an outlier score (views / that channel's median)."""
    if not rivals:
        return []
    channels = {ch["id"]: ch for ch in await yt.channels(c, ids=[r.channel_id for r in rivals])}
    out = []
    for r in rivals:
        uploads = ((channels.get(r.channel_id, {}).get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
        if not uploads:
            continue
        ids = await yt.playlist_video_ids(c, uploads, 20)
        vids = await yt.videos(c, ids, parts="snippet,statistics,contentDetails") if ids else []
        views = [sync._int((v.get("statistics") or {}).get("viewCount")) or 0 for v in vids]
        for v, n in zip(vids[:10], views[:10]):
            sn = v.get("snippet") or {}
            out.append({"channel": r.title, "title": sn.get("title"), "views": n, "age_days": _age_days(sn.get("publishedAt"), now),
                        "minutes": round((sync.seconds((v.get("contentDetails") or {}).get("duration")) or 0) / 60, 1),
                        "outlier": numbers.outlier(n, views)})
    out.sort(key=lambda x: x["outlier"] or 0, reverse=True)
    return out[:25]


async def run_ideas(*, engine: AsyncEngine, llm: LLM, yt: YouTubeClient, vault: TokenVault, tenant_id: uuid.UUID,
                    report_id: uuid.UUID) -> None:
    studio = await load(engine, tenant_id)
    try:
        now = datetime.now(UTC)
        c = creds(vault, studio)
        await sync.sync_videos(engine, yt, vault, studio)
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            videos = await sync.videos_of(db, studio)
            rivals = list((await db.scalars(select(YtCompetitor).where(
                YtCompetitor.connection_id == studio.connection_id, YtCompetitor.status == "active"))).all())
            lang = await report_language(db, studio.settings)
        category = Counter(v.category_id for v in videos if v.category_id).most_common(1)
        chart = await yt.most_popular(c, studio.settings.region, category[0][0] if category else None, 20)
        trending = [{"title": (v.get("snippet") or {}).get("title"), "channel": (v.get("snippet") or {}).get("channelTitle"),
                     "views": sync._int((v.get("statistics") or {}).get("viewCount")),
                     "age_days": _age_days((v.get("snippet") or {}).get("publishedAt"), now)} for v in chart]
        evidence = await competitor_evidence(yt, c, rivals, now)
        own_views = [v.views or 0 for v in videos]
        best = sorted(videos, key=lambda v: v.views or 0, reverse=True)[:6]
        s = studio.settings
        notes = await agents.trend_notes(llm, tenant_id, (
            f"Channel: {studio.connection.display_name}. About: {s.about or 'not described'}. Audience: {s.audience or 'not described'}. "
            f"Country: {s.region}. Languages: {', '.join(s.languages)}. Recent titles: "
            + "; ".join(v.title for v in videos[:8])
        ))
        channel = studio.channel_block() | {"best_videos": [
            {"title": v.title, "views": v.views, "outlier": numbers.outlier(v.views or 0, own_views), "short": v.is_short} for v in best]}
        text = (
            f"<report_language>{lang}</report_language>\n<channel>\n{reports.dumps(channel)}\n</channel>\n"
            f"<trending>\n{reports.dumps([{'n': i + 1, **t} for i, t in enumerate(trending)])}\n</trending>\n"
            f"<competitors>\n{reports.dumps([{'n': i + 1, **e} for i, e in enumerate(evidence)])}\n</competitors>\n"
            f"<web_notes>\n{notes.text}\n\nSources:\n"
            + "\n".join(f"[{i + 1}] {src.title} {src.url}" for i, src in enumerate(notes.sources)) + "\n</web_notes>"
        )
        result = await agents.ideas(llm, tenant_id, text)
        out = result.output
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            for idea in out.ideas:
                db.add(YtIdea(idea_id=uuid.uuid4(), tenant_id=tenant_id, connection_id=studio.connection_id, report_id=report_id,
                              title=idea.title, data=idea.model_dump(exclude={"title"}) | {"lang": lang}))
        cost = (result.cost_usd or 0) + (notes.cost_usd or 0)
        await reports.finish(engine, tenant_id, report_id, status="done", output=out.model_dump() | {"lang": lang},
                             input={"trending": trending, "competitors": evidence}, cost_usd=cost,
                             sources=[{"title": src.title, "url": src.url} for src in notes.sources])
    except Exception as e:  # noqa: BLE001
        await reports._fail(engine, tenant_id, report_id, e)
