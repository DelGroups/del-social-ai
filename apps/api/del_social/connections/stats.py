"""Channel numbers for the home page cards: one snapshot per connection per day (migration 0019).

Code collects and counts everything (CLAUDE.md principle 2); growth is the difference between
two stored snapshots, never an estimate. One request per channel per day keeps us far from any
rate limit, and nothing is sent to Meta while the owner's switch is off (ADR 011): the cards
then show the last stored numbers.

Each channel has a reader: (credentials, now) → values for the row, or None when that channel
has nothing to count (a Telegram bot). A failed read keeps yesterday's numbers and never marks
the connection as broken; the daily research and the Test button judge connections.
"""
import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.connections.base import ChannelError, Credentials
from del_social.connections.meta import MetaClient
from del_social.connections.service import credentials
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault, VaultError
from del_social.models import Channel, ChannelStat, Connection
from del_social.team import timing

log = logging.getLogger(__name__)

COLLECT_AT = time(7, 30)  # Baku; before the morning research at 08:00
CHECK_SECONDS = 600
RECENT = 12  # posts whose likes and comments are summed

Reader = Callable[[Credentials, datetime], Awaitable[dict[str, Any] | None]]


def baku_day(now: datetime) -> date:
    return now.astimezone(timing.BAKU).date()


def _int(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def meta_readers(meta: MetaClient | None) -> dict[str, Reader]:
    """Instagram and Facebook readers; none while Meta is not configured or paused by the owner."""
    if meta is None or meta.paused:
        return {}

    async def instagram(creds: Credentials, now: datetime) -> dict[str, Any]:
        d = await meta.api(
            creds.external_id, creds.token,
            fields=f"username,name,followers_count,follows_count,media_count,profile_picture_url,media.limit({RECENT}){{like_count,comments_count,timestamp}}",
        )
        media = (d.get("media") or {}).get("data") or []
        return {
            "followers": _int(d.get("followers_count")), "posts": _int(d.get("media_count")),
            "likes": sum(_int(m.get("like_count")) or 0 for m in media),
            "comments": sum(_int(m.get("comments_count")) or 0 for m in media),
            "extra": {"username": d.get("username"), "name": d.get("name"), "avatar": d.get("profile_picture_url"),
                      "following": _int(d.get("follows_count")), "recent": len(media)},
        }

    async def facebook(creds: Credentials, now: datetime) -> dict[str, Any]:
        d = await meta.api(creds.external_id, creds.token, fields="name,link,followers_count,fan_count,picture.type(large){url}")
        return {
            "followers": _int(d.get("followers_count")) or _int(d.get("fan_count")),
            "extra": {"name": d.get("name"), "link": d.get("link"), "avatar": ((d.get("picture") or {}).get("data") or {}).get("url"),
                      "fans": _int(d.get("fan_count"))},
        }

    return {Channel.INSTAGRAM.value: instagram, Channel.FACEBOOK.value: facebook}


async def save(db: AsyncSession, conn: Connection, day: date, values: dict[str, Any]) -> None:
    row = {k: values.get(k) for k in ("followers", "posts", "views", "likes", "comments")}
    row["extra"] = {k: v for k, v in (values.get("extra") or {}).items() if v is not None}
    stmt = insert(ChannelStat).values(tenant_id=conn.tenant_id, connection_id=conn.connection_id, day=day, **row)
    await db.execute(stmt.on_conflict_do_update(
        constraint="uq_channel_stats_connection_day", set_={**row, "collected_at": datetime.now(UTC)},
    ))


async def collect_tenant(
    engine: AsyncEngine, vault: TokenVault, readers: dict[str, Reader], tenant_id: uuid.UUID,
    now: datetime | None = None, force: bool = False,
) -> int:
    """Today's snapshot of every connection that has a reader; returns how many were stored."""
    now = now or datetime.now(UTC)
    day = baku_day(now)
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        conns = (await db.scalars(select(Connection).where(Connection.channel.in_(list(readers))))).all()
        done = set((await db.scalars(select(ChannelStat.connection_id).where(ChannelStat.day == day))).all())
    stored = 0
    for conn in conns:
        if conn.connection_id in done and not force:
            continue
        try:
            values = await readers[conn.channel](credentials(vault, conn), now)
        except (ChannelError, VaultError) as e:
            log.warning("channel stats failed for %s %s: %s", conn.channel, conn.connection_id, e)
            continue
        if values is None:
            continue
        async with AsyncSession(engine) as db, db.begin():
            await set_tenant(db, tenant_id)
            await save(db, conn, day, values)
        stored += 1
    return stored


async def tick(
    *, engine: AsyncEngine, vault: TokenVault, readers: dict[str, Reader], now: datetime | None = None,
) -> int:
    now = now or datetime.now(UTC)
    if now.astimezone(timing.BAKU).time() < COLLECT_AT or not readers:
        return 0
    async with AsyncSession(engine) as db, db.begin():
        ids = [r[0] for r in (await db.execute(text("SELECT tenant_id FROM stats_tenants()"))).all()]
    total = 0
    for tenant_id in ids:
        try:
            total += await collect_tenant(engine, vault, readers, uuid.UUID(str(tenant_id)), now)
        except Exception:
            log.exception("channel stats round failed for %s", tenant_id)
    return total


async def loop(*, engine: AsyncEngine, vault: TokenVault, readers: dict[str, Reader]) -> None:
    while True:
        try:
            await tick(engine=engine, vault=vault, readers=readers)
        except Exception:
            log.exception("channel stats round failed")
        await asyncio.sleep(CHECK_SECONDS)


def growth(rows: list[ChannelStat], days: int) -> int | None:
    """Followers now minus followers `days` ago (the closest earlier snapshot). rows: newest first."""
    if not rows or rows[0].followers is None:
        return None
    target = rows[0].day - timedelta(days=days)
    past = next((r for r in rows if r.day <= target and r.followers is not None), None)
    return None if past is None else rows[0].followers - past.followers
