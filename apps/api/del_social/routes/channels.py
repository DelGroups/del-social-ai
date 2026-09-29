"""The channel cards on the home page: each connected channel with its latest numbers and growth."""
import uuid
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.connections import stats
from del_social.core.config import get_settings
from del_social.core.deps import TenantContext, get_db, require_permission
from del_social.models import Channel, ChannelStat, Connection
from del_social.tenants.permissions import Permission

router = APIRouter(prefix="/tenants/{tenant_id}/channels", tags=["channels"])

can_view = require_permission(Permission.VIEW)
HISTORY_DAYS = 30
META = (Channel.INSTAGRAM.value, Channel.FACEBOOK.value)


class Point(BaseModel):
    day: date
    followers: int | None


class ChannelCard(BaseModel):
    connection_id: uuid.UUID
    channel: str
    name: str
    status: str
    paused: bool  # Meta switched off by the owner: numbers are the last stored ones
    avatar: str | None
    url: str | None
    day: date | None
    collected_at: datetime | None
    followers: int | None
    posts: int | None
    views: int | None
    likes: int | None
    comments: int | None
    recent: int | None  # how many recent posts the likes and comments cover
    engagement_rate: float | None  # (likes + comments) per recent post / followers, in %
    growth_7d: int | None
    growth_30d: int | None
    series: list[Point]
    extra: dict[str, Any]


def _url(conn: Connection, extra: dict[str, Any]) -> str | None:
    if conn.channel == Channel.INSTAGRAM.value:
        name = extra.get("username") or conn.display_name.lstrip("@")
        return f"https://instagram.com/{name}"
    if conn.channel == Channel.FACEBOOK.value:
        return extra.get("link") or f"https://facebook.com/{conn.external_id}"
    if conn.channel == Channel.YOUTUBE.value:
        handle = extra.get("handle")
        return f"https://youtube.com/{handle}" if handle else f"https://youtube.com/channel/{conn.external_id}"
    return None


def card(conn: Connection, rows: list[ChannelStat], paused: bool) -> ChannelCard:
    """rows: this connection's snapshots, newest first. Every number is stored or computed here."""
    last = rows[0] if rows else None
    extra = dict(last.extra) if last else {}
    recent = extra.get("recent")
    rate = None
    if last and last.followers and recent and last.likes is not None:
        rate = round((last.likes + (last.comments or 0)) / recent / last.followers * 100, 2)
    elif last and extra.get("engagement_rate") is not None:  # history from the morning research
        rate = float(extra["engagement_rate"])
    since = last.day - timedelta(days=HISTORY_DAYS) if last else None
    return ChannelCard(
        connection_id=conn.connection_id, channel=conn.channel,
        name=extra.get("name") or extra.get("title") or conn.display_name, status=conn.status, paused=paused,
        avatar=extra.get("avatar"), url=_url(conn, extra),
        day=last.day if last else None, collected_at=last.collected_at if last else None,
        followers=last.followers if last else None, posts=last.posts if last else None,
        views=last.views if last else None, likes=last.likes if last else None,
        comments=last.comments if last else None, recent=recent, engagement_rate=rate,
        growth_7d=stats.growth(rows, 7), growth_30d=stats.growth(rows, 30),
        series=[Point(day=r.day, followers=r.followers) for r in reversed(rows) if since and r.day >= since],
        extra={k: v for k, v in extra.items() if k not in ("avatar", "source")},
    )


@router.get("", response_model=list[ChannelCard])
async def overview(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> list[ChannelCard]:
    conns = (await db.scalars(
        select(Connection).where(Connection.channel != Channel.TELEGRAM.value).order_by(Connection.created_at)
    )).all()
    # Enough history for 30-day growth of every channel (one row per channel per day)
    rows = (await db.scalars(
        select(ChannelStat).order_by(ChannelStat.day.desc()).limit((HISTORY_DAYS + 31) * max(1, len(conns)))
    )).all()
    paused = get_settings().meta_paused
    return [
        card(c, [r for r in rows if r.connection_id == c.connection_id], paused and c.channel in META)
        for c in conns
    ]
