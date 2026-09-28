"""The studio's rhythm for every company with YouTube Studio and a connected channel.

Every 10 minutes: videos are synced every 3 hours, the pulse runs at the owner's rhythm (every 3, 6
or 12 hours), the daily report once a day at the owner's hour (Baku time), and new comments are
fetched every 2 hours. All of it is free for the company (cheap models, few API units); the costly
work (review, ideas, thumbnails, video) only runs when a person asks and pays credits.
"""
import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.connections.youtube import YouTubeClient, YouTubeError
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.llm import LLM
from del_social.models import Connection, ConnectionStatus, YtReply, YtVideo
from del_social.team import timing
from del_social.youtube import comments, reports, sync
from del_social.youtube.channel import Studio, load

log = logging.getLogger(__name__)

CHECK_SECONDS = 600
SYNC_EVERY = timedelta(hours=3)
COMMENTS_EVERY = timedelta(hours=2)
_last_comments: dict[uuid.UUID, datetime] = {}


async def _mark(engine: AsyncEngine, studio: Studio, error: str | None) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        conn = await db.get(Connection, studio.connection_id)
        conn.status = ConnectionStatus.ERROR.value if error else ConnectionStatus.ACTIVE.value
        conn.last_error = error
        conn.last_checked_at = datetime.now(UTC)


async def tick_tenant(*, engine: AsyncEngine, llm: LLM | None, yt: YouTubeClient, vault: TokenVault, http: httpx.AsyncClient,
                      tenant_id: uuid.UUID, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(UTC)
    studio = await load(engine, tenant_id)
    if studio is None:
        return []
    done: list[str] = []
    s = studio.settings
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            last_sync = await db.scalar(select(func.max(YtVideo.synced_at)).where(YtVideo.connection_id == studio.connection_id))
            pulse = await reports.latest(db, studio.connection_id, "pulse")
            daily = await reports.latest(db, studio.connection_id, "daily")
        if last_sync is None or now - last_sync >= SYNC_EVERY:
            await sync.sync_videos(engine, yt, vault, studio, now)
            done.append("sync")
        if llm is not None and s.pulse_hours and (pulse is None or now - pulse.created_at >= timedelta(hours=s.pulse_hours, minutes=-5)):
            rid = await reports.create(engine, studio, "pulse", period=(now - timedelta(hours=s.pulse_hours), now), now=now)
            await reports.run_pulse(engine=engine, llm=llm, yt=yt, vault=vault, tenant_id=tenant_id, report_id=rid,
                                    hours=s.pulse_hours, now=now)
            done.append("pulse")
        local = now.astimezone(timing.BAKU)
        if llm is not None and s.daily_report and local.hour >= s.daily_at and (
                daily is None or daily.created_at.astimezone(timing.BAKU).date() < local.date()):
            rid = await reports.create(engine, studio, "daily", now=now)
            await reports.run_daily(engine=engine, llm=llm, yt=yt, vault=vault, tenant_id=tenant_id, report_id=rid)
            done.append("daily")
        if now - _last_comments.get(studio.connection_id, datetime.min.replace(tzinfo=UTC)) >= COMMENTS_EVERY:
            _last_comments[studio.connection_id] = now
            await comments.fetch(engine, yt, vault, studio)
            done.append("comments")
        if studio.connection.status != ConnectionStatus.ACTIVE.value:
            await _mark(engine, studio, None)
    except YouTubeError as e:
        if e.auth:
            await _mark(engine, studio, str(e))
        log.warning("youtube round for %s: %s", tenant_id, e)
    return done


async def tick(*, engine: AsyncEngine, llm: LLM | None, yt: YouTubeClient, vault: TokenVault, http: httpx.AsyncClient) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        ids = [r[0] for r in (await db.execute(text("SELECT tenant_id FROM addon_tenants('youtube')"))).all()]
    for tenant_id in ids:
        try:
            await tick_tenant(engine=engine, llm=llm, yt=yt, vault=vault, http=http, tenant_id=uuid.UUID(str(tenant_id)))
        except Exception:
            log.exception("youtube round failed for %s", tenant_id)


async def loop(*, engine: AsyncEngine, llm: LLM | None, yt: YouTubeClient, vault: TokenVault, http: httpx.AsyncClient) -> None:
    while True:
        try:
            await tick(engine=engine, llm=llm, yt=yt, vault=vault, http=http)
        except Exception:
            log.exception("youtube round failed")
        await asyncio.sleep(CHECK_SECONDS)


async def waiting_replies(db: AsyncSession, connection_id: uuid.UUID) -> int:
    return await db.scalar(select(func.count()).where(YtReply.connection_id == connection_id, YtReply.status.in_(("new", "drafted")))) or 0
