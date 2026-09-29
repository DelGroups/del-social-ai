"""Reports for the creator: the pulse (last hours), the daily report, and the deep channel review.

Code collects and computes every number (numbers.py); the model only reads them and writes. A
report row is created (and paid for, when it costs credits) before the work starts; work that fails
is marked failed and its credits are refunded.
"""
import json
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents import youtube as agents
from del_social.billing import credits
from del_social.connections.youtube import PACIFIC, YouTubeClient, YouTubeError
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.llm import LLM, LLMError
from del_social.models import YtCompetitor, YtReport, YtVideo
from del_social.team import timing
from del_social.youtube import numbers, sync
from del_social.youtube.channel import Studio, creds, load, report_language

log = logging.getLogger(__name__)

THUMB_BYTES = 400_000
FIRST_PULSE = {
    "az": {"headline": "İlk ölçü götürüldü", "summary": "Kanal indicə qoşuldu: videoların baxış sayı yadda saxlanıldı. Növbəti nəbz bu rəqəmlərlə müqayisə edib son saatlarda nə dəyişdiyini göstərəcək.", "highlights": [], "actions": []},
    "ru": {"headline": "Первый замер сделан", "summary": "Канал только что подключён: просмотры видео сохранены. Следующий пульс сравнит с ними и покажет, что изменилось за последние часы.", "highlights": [], "actions": []},
    "en": {"headline": "First measurement taken", "summary": "The channel was just connected: its videos' view counts are saved. The next pulse compares with them and shows what changed in the last hours.", "highlights": [], "actions": []},
    "fa": {"headline": "اولین اندازه‌گیری انجام شد", "summary": "کانال همین حالا وصل شد و تعداد بازدید ویدیوها ذخیره شد. نبض بعدی با همین اعداد مقایسه می‌کند و نشان می‌دهد در چند ساعت اخیر چه تغییری کرده است.", "highlights": [], "actions": []},
}


def dumps(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, indent=1, default=str)


async def create(engine: AsyncEngine, studio: Studio, kind: str, *, cost: int = 0, by: uuid.UUID | None = None,
                 period: tuple[datetime | None, datetime | None] = (None, None), now: datetime | None = None) -> uuid.UUID:
    """A report row, committed, and its credits spent (raises CreditError before anything starts)."""
    rid = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        if cost:
            await credits.spend(db, studio.tenant_id, cost, kind, rid, by)
        db.add(YtReport(report_id=rid, tenant_id=studio.tenant_id, connection_id=studio.connection_id, kind=kind,
                        credits=cost, period_start=period[0], period_end=period[1], requested_by=by,
                        created_at=now or datetime.now(UTC)))
    return rid


async def finish(engine: AsyncEngine, tenant_id: uuid.UUID, rid: uuid.UUID, **values: Any) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        r = await db.get(YtReport, rid)
        for k, v in values.items():
            setattr(r, k, v)
        r.finished_at = datetime.now(UTC)
        if values.get("status") == "failed" and r.credits:
            await credits.refund(db, tenant_id, rid)


async def _fail(engine: AsyncEngine, tenant_id: uuid.UUID, rid: uuid.UUID, e: Exception) -> None:
    text = str(e) if isinstance(e, (YouTubeError, LLMError)) else "Something went wrong; the credits were refunded."
    log.warning("youtube report %s failed: %s", rid, e)
    await finish(engine, tenant_id, rid, status="failed", error=text[:500])


def analytics_today() -> date:
    return datetime.now(PACIFIC).date()


async def run_pulse(*, engine: AsyncEngine, llm: LLM, yt: YouTubeClient, vault: TokenVault, tenant_id: uuid.UUID,
                    report_id: uuid.UUID, hours: int, now: datetime | None = None) -> None:
    studio = await load(engine, tenant_id)
    now = now or datetime.now(UTC)
    try:
        await sync.sync_videos(engine, yt, vault, studio, now)
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            facts = await numbers.last_hours(db, studio.connection_id, hours, now)
            lang = await report_language(db, studio.settings)
        if facts["videos_compared"] == 0:
            # No earlier snapshot to compare with yet (first pulse after connecting): say so, don't ask a model
            await finish(engine, tenant_id, report_id, status="done", input=facts, output=FIRST_PULSE[lang] | {"lang": lang})
            return
        text = (f"<report_language>{lang}</report_language>\n<kind>pulse</kind>\n<channel>\n{dumps(studio.channel_block())}\n</channel>\n"
                f"<facts>\n{dumps(facts)}\n</facts>")
        result = await agents.report(llm, tenant_id, text)
        await finish(engine, tenant_id, report_id, status="done", input=facts, output=result.output.model_dump() | {"lang": lang},
                     cost_usd=result.cost_usd)
    except Exception as e:  # noqa: BLE001 — a report never breaks the loop
        await _fail(engine, tenant_id, report_id, e)


async def run_daily(*, engine: AsyncEngine, llm: LLM, yt: YouTubeClient, vault: TokenVault, tenant_id: uuid.UUID,
                    report_id: uuid.UUID) -> None:
    studio = await load(engine, tenant_id)
    try:
        c = numbers.Collector(yt, creds(vault, studio))
        today = analytics_today()
        facts = await numbers.daily(c, today)
        facts["last_28_days"] = await numbers.period(c, today - timedelta(days=28), today, "28 days")
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            titles = {v.video_id: v.title for v in await sync.videos_of(db, studio)}
            lang = await report_language(db, studio.settings)
        for v in facts.get("top_videos") or []:
            v["title"] = titles.get(v["video_id"], v["video_id"])
        facts["data_gaps"] = c.gaps
        text = (f"<report_language>{lang}</report_language>\n<kind>daily</kind>\n<channel>\n{dumps(studio.channel_block())}\n</channel>\n"
                f"<facts>\n{dumps(facts)}\n</facts>")
        result = await agents.report(llm, tenant_id, text)
        await finish(engine, tenant_id, report_id, status="done", input=facts, output=result.output.model_dump() | {"lang": lang},
                     cost_usd=result.cost_usd)
    except Exception as e:  # noqa: BLE001
        await _fail(engine, tenant_id, report_id, e)


async def _thumb(http: httpx.AsyncClient, url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        r = await http.get(url, timeout=20.0)
    except httpx.HTTPError:
        return None
    return r.content if r.status_code == 200 and len(r.content) <= THUMB_BYTES else None


def video_line(v: YtVideo, stats: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"video_id": v.video_id, "title": v.title, "published": v.published_at.date().isoformat() if v.published_at else None,
            "minutes": round((v.duration_s or 0) / 60, 1), "short": v.is_short, "views": v.views, "likes": v.likes,
            "comments": v.comments, **({"last_90_days": stats} if stats else {})}


async def run_review(*, engine: AsyncEngine, llm: LLM, yt: YouTubeClient, vault: TokenVault, http: httpx.AsyncClient,
                     tenant_id: uuid.UUID, report_id: uuid.UUID) -> None:
    studio = await load(engine, tenant_id)
    try:
        now = datetime.now(UTC)
        await sync.sync_videos(engine, yt, vault, studio)
        c = numbers.Collector(yt, creds(vault, studio))
        today = analytics_today()
        facts: dict[str, Any] = {
            "last_28_days": await numbers.period(c, today - timedelta(days=28), today, "28 days"),
            "previous_28_days": await numbers.period(c, today - timedelta(days=56), today - timedelta(days=29), "previous 28 days"),
            "last_90_days": await numbers.period(c, today - timedelta(days=90), today, "90 days"),
            "breakdown_last_90_days": await numbers.breakdowns(c, today - timedelta(days=90), today),
        }
        per_video = await numbers.per_video(c, today - timedelta(days=90), today)
        if money := await numbers.revenue(c, today - timedelta(days=28), today):
            facts["revenue_last_28_days"] = money
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            videos = await sync.videos_of(db, studio)
            rivals = (await db.scalars(select(YtCompetitor).where(YtCompetitor.connection_id == studio.connection_id,
                                                                   YtCompetitor.status == "active"))).all()
            lang = await report_language(db, studio.settings)
        facts["upload_rhythm"] = numbers.cadence(videos, now)
        facts["formats"] = numbers.formats(videos)
        ranked = sorted((v for v in videos if v.video_id in per_video and not v.is_short),
                        key=lambda v: per_video[v.video_id]["views"], reverse=True)
        best, weakest = ranked[:4], [v for v in ranked[-3:] if v not in ranked[:4]]
        for v in best[:2] + weakest[-1:]:
            if r := await numbers.retention(c, v.video_id, today - timedelta(days=90), today):
                per_video[v.video_id]["retention"] = r
        facts["best_videos_last_90_days"] = [video_line(v, per_video[v.video_id]) for v in best]
        facts["weakest_videos_last_90_days"] = [video_line(v, per_video[v.video_id]) for v in weakest]
        facts["data_gaps"] = c.gaps
        shown = best[:3] + weakest[-3:]
        images = [b for v in shown if (b := await _thumb(http, v.thumbnail_url))]
        text = (
            f"<report_language>{lang}</report_language>\n<channel>\n{dumps(studio.channel_block())}\n</channel>\n"
            f"<facts>\n{dumps(facts)}\n</facts>\n"
            f"<videos>\n{dumps([video_line(v) for v in videos[:30]])}\n</videos>\n"
            f"<competitors>\n{dumps([{'title': r.title, 'handle': r.handle, 'subscribers': r.subscribers, 'videos': r.videos, 'views': r.views} for r in rivals])}\n</competitors>\n"
            f"<thumbnails>{dumps([v.title for v in shown][:len(images)])}</thumbnails>"
        )
        result = await agents.review(llm, tenant_id, text, images)
        await finish(engine, tenant_id, report_id, status="done", input=facts, output=result.output.model_dump() | {"lang": lang},
                     cost_usd=result.cost_usd)
    except Exception as e:  # noqa: BLE001
        await _fail(engine, tenant_id, report_id, e)


async def latest(db: AsyncSession, connection_id: uuid.UUID, kind: str) -> YtReport | None:
    return await db.scalar(select(YtReport).where(YtReport.connection_id == connection_id, YtReport.kind == kind)
                           .order_by(YtReport.created_at.desc()).limit(1))


def baku_day(now: datetime) -> date:
    return now.astimezone(timing.BAKU).date()
