"""The channel's videos and their counts, copied from YouTube (a few units per run).

A snapshot of every video's views, likes and comments is kept at each sync, so "views in the last
hours" is a difference of two stored numbers (computed by code). Snapshots older than 35 days are
removed.
"""
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.connections.youtube import YouTubeClient
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.models import YtVideo, YtVideoSnapshot
from del_social.youtube.channel import Studio, creds

MAX_VIDEOS = 200
KEEP_SNAPSHOTS = timedelta(days=35)
SHORT_MAX_S = 180  # YouTube Shorts can be up to 3 minutes
_DURATION = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def seconds(iso: str | None) -> int | None:
    """ISO 8601 duration (PT1H2M3S) → seconds."""
    m = _DURATION.match(iso or "")
    if not m:
        return None
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return ((d * 24 + h) * 60 + mi) * 60 + s


def _ts(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _thumb(sn: dict[str, Any]) -> str | None:
    t = sn.get("thumbnails") or {}
    for k in ("maxres", "standard", "high", "medium", "default"):
        if (t.get(k) or {}).get("url"):
            return t[k]["url"]
    return None


def row_of(item: dict[str, Any]) -> dict[str, Any]:
    sn, st, cd, status = (item.get(k) or {} for k in ("snippet", "statistics", "contentDetails", "status"))
    dur = seconds(cd.get("duration"))
    text = f"{sn.get('title', '')} {sn.get('description', '')}".lower()
    return {
        "video_id": item["id"], "title": sn.get("title") or "", "description": sn.get("description") or "",
        "tags": sn.get("tags") or [], "category_id": sn.get("categoryId"),
        "language": sn.get("defaultAudioLanguage") or sn.get("defaultLanguage"),
        "published_at": _ts(sn.get("publishedAt")), "duration_s": dur, "privacy": status.get("privacyStatus"),
        "publish_at": _ts(status.get("publishAt")),
        "is_short": dur is not None and (dur <= 60 or (dur <= SHORT_MAX_S and "#short" in text)),
        "thumbnail_url": _thumb(sn), "views": _int(st.get("viewCount")), "likes": _int(st.get("likeCount")),
        "comments": _int(st.get("commentCount")), "has_captions": cd.get("caption") == "true",
    }


async def sync_videos(engine: AsyncEngine, yt: YouTubeClient, vault: TokenVault, studio: Studio,
                      now: datetime | None = None) -> int:
    """Copy the channel's latest videos and store a snapshot of their counts. Returns how many."""
    now = (now or datetime.now(UTC)).replace(second=0, microsecond=0)
    if not studio.uploads:
        return 0
    c = creds(vault, studio)
    ids = await yt.playlist_video_ids(c, studio.uploads, MAX_VIDEOS)
    items = await yt.videos(c, ids) if ids else []
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        for item in items:
            row = row_of(item)
            stmt = insert(YtVideo).values(tenant_id=studio.tenant_id, connection_id=studio.connection_id, synced_at=now, **row)
            await db.execute(stmt.on_conflict_do_update(
                constraint="pk_yt_videos", set_={k: v for k, v in row.items() if k != "video_id"} | {"synced_at": now},
            ))
            await db.execute(insert(YtVideoSnapshot).values(
                tenant_id=studio.tenant_id, connection_id=studio.connection_id, video_id=row["video_id"], at=now,
                views=row["views"], likes=row["likes"], comments=row["comments"],
            ).on_conflict_do_nothing())
        await db.execute(delete(YtVideoSnapshot).where(
            YtVideoSnapshot.connection_id == studio.connection_id, YtVideoSnapshot.at < now - KEEP_SNAPSHOTS,
        ))
    return len(items)


async def videos_of(db: AsyncSession, studio: Studio) -> list[YtVideo]:
    return list((await db.scalars(select(YtVideo).where(YtVideo.connection_id == studio.connection_id)
                                  .order_by(YtVideo.published_at.desc().nullslast()))).all())
