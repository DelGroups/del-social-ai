"""The YouTube team: the owner talks to the Channel Manager, who hands work to the team (ADR 012).

The manager (yt_lead) answers and picks actions from a fixed menu; code checks every action (the
video exists, credits are enough) and starts the same work the panel's buttons start. When a piece of
work finishes, the team member who did it reports back in the chat with a link to the result.
Principles 1, 2 and 4: the model never touches YouTube, the database or credits itself.
"""
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents import youtube as agents
from del_social.billing import credits
from del_social.billing.quota import QuotaError
from del_social.connections import stats
from del_social.connections.youtube import YouTubeClient, YouTubeError
from del_social.core.config import Settings
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.llm import LLM, LLMError
from del_social.media.fal import FalClient
from del_social.models import ChannelStat, YtChat, YtDraft, YtIdea, YtJob, YtReply, YtReport, YtThumbnail, YtVideo
from del_social.team import lead as social_lead
from del_social.team import texts
from del_social.youtube import comments, ideas, kit, render, reports, sync, thumbs
from del_social.youtube.channel import load

log = logging.getLogger(__name__)

HISTORY = 14
ROSTER = ("yt_lead", "yt_reporter", "yt_reviewer", "yt_ideas", "yt_metadata", "yt_thumbnail", "yt_replies", "yt_editor")
_busy: set[uuid.UUID] = set()  # companies whose manager is thinking right now

# What each team member says when work is started, done or failed (code writes these, in the owner's language)
MSG: dict[str, dict[str, str]] = {
    "started": {"az": "{who} işə başladı: {what}.", "ru": "{who} начал работу: {what}.", "en": "{who} started: {what}.",
                "fa": "{who} کار را شروع کرد: {what}."},
    "done_report": {"az": "Hazırdır: {headline}", "ru": "Готово: {headline}", "en": "Ready: {headline}", "fa": "آماده است: {headline}"},
    "done_ideas": {"az": "{n} yeni ideya hazırdır.", "ru": "Готово {n} новых идей.", "en": "{n} new ideas are ready.", "fa": "{n} ایده‌ی تازه آماده است."},
    "done_kit": {"az": "«{title}» üçün mətnlər hazırdır (SEO {score}). Videonun səhifəsində baxıb YouTube-a göndərə bilərsiniz.",
                 "ru": "Тексты для «{title}» готовы (SEO {score}). Посмотрите на странице видео и отправьте на YouTube.",
                 "en": "The kit for “{title}” is ready (SEO {score}). Check it on the video's page and send it to YouTube.",
                 "fa": "متن‌های «{title}» آماده است (سئو {score}). در صفحه‌ی ویدیو ببینید و به یوتیوب بفرستید."},
    "done_thumbs": {"az": "«{title}» üçün 3 thumbnail dizaynı hazırdır.", "ru": "3 дизайна обложки для «{title}» готовы.",
                    "en": "3 thumbnail designs for “{title}” are ready.", "fa": "۳ طرح تامبنیل برای «{title}» آماده است."},
    "done_comments": {"az": "{n} şərhə cavab qaralaması yazıldı. Şərhlər bölməsində baxıb göndərin.",
                      "ru": "Написаны черновики ответов на {n} комментариев. Проверьте и отправьте во вкладке «Комментарии».",
                      "en": "Reply drafts written for {n} comments. Check and send them in the Comments tab.",
                      "fa": "برای {n} کامنت پیش‌نویس جواب نوشته شد. در بخش کامنت‌ها ببینید و بفرستید."},
    "no_comments": {"az": "Cavab gözləyən yeni şərh yoxdur.", "ru": "Новых комментариев без ответа нет.", "en": "No new comments are waiting.",
                    "fa": "کامنت تازه‌ای منتظر جواب نیست."},
    "done_sync": {"az": "Kanal yeniləndi: {videos} video.", "ru": "Канал обновлён: {videos} видео.", "en": "Channel refreshed: {videos} videos.",
                  "fa": "کانال به‌روز شد: {videos} ویدیو."},
    "done_rivals": {"az": "İzləməyə əlavə edildi: {added}.{missing}", "ru": "Добавлены в отслеживание: {added}.{missing}",
                    "en": "Now watching: {added}.{missing}", "fa": "به فهرست رقبا اضافه شد: {added}.{missing}"},
    "missing": {"az": " Tapılmadı: {list}.", "ru": " Не найдены: {list}.", "en": " Not found: {list}.", "fa": " پیدا نشد: {list}."},
    "failed": {"az": "Alınmadı: {error}", "ru": "Не получилось: {error}", "en": "That didn't work: {error}", "fa": "انجام نشد: {error}"},
    "no_video": {"az": "Bu videonu kanalda tapa bilmədim.", "ru": "Не нашёл это видео на канале.", "en": "I couldn't find that video on the channel.",
                 "fa": "این ویدیو را در کانال پیدا نکردم."},
    "no_ai": {"az": "Komanda hələ qurulmayıb (AI açarı yoxdur).", "ru": "Команда ещё не настроена (нет ключа ИИ).",
              "en": "The team is not set up on this server yet (no AI key).", "fa": "تیم هنوز روی سرور راه‌اندازی نشده (کلید هوش مصنوعی نیست)."},
}
WHAT = {
    "sync": {"az": "kanalın yenilənməsi", "ru": "обновление канала", "en": "refreshing the channel", "fa": "به‌روزرسانی کانال"},
    "pulse": {"az": "nəbz hesabatı", "ru": "пульс", "en": "the pulse report", "fa": "گزارش نبض"},
    "daily": {"az": "gündəlik hesabat", "ru": "ежедневный отчёт", "en": "the daily report", "fa": "گزارش روزانه"},
    "review": {"az": "kanalın dərin təhlili", "ru": "глубокий разбор канала", "en": "the deep channel review", "fa": "بررسی عمیق کانال"},
    "ideas": {"az": "yeni video ideyaları", "ru": "новые идеи для видео", "en": "new video ideas", "fa": "ایده‌های تازه‌ی ویدیو"},
    "kit": {"az": "başlıq, təsvir və teqlər", "ru": "заголовок, описание и теги", "en": "title, description and tags", "fa": "عنوان، توضیحات و تگ‌ها"},
    "thumbnails": {"az": "3 thumbnail dizaynı", "ru": "3 дизайна обложки", "en": "3 thumbnail designs", "fa": "۳ طرح تامبنیل"},
    "comments": {"az": "şərhlərə cavab qaralamaları", "ru": "черновики ответов на комментарии", "en": "reply drafts for comments", "fa": "پیش‌نویس جواب کامنت‌ها"},
}
WHO = {  # which team member does each action
    "sync": "yt_reporter", "pulse": "yt_reporter", "daily": "yt_reporter", "review": "yt_reviewer", "ideas": "yt_ideas",
    "kit": "yt_metadata", "thumbnails": "yt_thumbnail", "comments": "yt_replies", "add_competitors": "yt_ideas",
}
NAMES = {
    "yt_lead": {"az": "Kanal meneceri", "ru": "Менеджер канала", "en": "Channel manager", "fa": "مدیر کانال"},
    "yt_reporter": {"az": "Analitik", "ru": "Аналитик", "en": "Analyst", "fa": "تحلیلگر"},
    "yt_reviewer": {"az": "Strateq", "ru": "Стратег", "en": "Strategist", "fa": "استراتژیست"},
    "yt_ideas": {"az": "İdeya prodüseri", "ru": "Продюсер идей", "en": "Ideas producer", "fa": "تهیه‌کننده‌ی ایده"},
    "yt_metadata": {"az": "SEO kopirayter", "ru": "SEO-копирайтер", "en": "SEO copywriter", "fa": "کپی‌رایتر سئو"},
    "yt_thumbnail": {"az": "Thumbnail dizayneri", "ru": "Дизайнер обложек", "en": "Thumbnail designer", "fa": "طراح تامبنیل"},
    "yt_replies": {"az": "İcma meneceri", "ru": "Комьюнити-менеджер", "en": "Community manager", "fa": "مدیر جامعه"},
    "yt_editor": {"az": "Video montajçı", "ru": "Видеомонтажёр", "en": "Video editor", "fa": "تدوینگر ویدیو"},
}


class Crew:
    """Everything the team's work needs (built by the route; background work keeps its own sessions)."""

    def __init__(self, *, engine: AsyncEngine, settings: Settings, tenant_id: uuid.UUID, llm: LLM | None, yt: YouTubeClient | None,
                 vault: TokenVault | None, http: httpx.AsyncClient, fal: FalClient | None, by: uuid.UUID | None):
        self.engine, self.settings, self.tenant_id, self.llm, self.yt = engine, settings, tenant_id, llm, yt
        self.vault, self.http, self.fal, self.by = vault, http, fal, by


def say_text(key: str, lang: str, **kw: Any) -> str:
    return MSG[key].get(lang, MSG[key]["en"]).format(**kw)


async def say(engine: AsyncEngine, tenant_id: uuid.UUID, agent: str, text: str, payload: dict[str, Any] | None = None) -> None:
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        db.add(YtChat(message_id=uuid.uuid4(), tenant_id=tenant_id, role="agent", agent=agent, text=text[:4000], payload=payload))


async def _lang(engine: AsyncEngine, tenant_id: uuid.UUID) -> str:
    """The language the owner writes to the team in (their latest message), else the channel's report language."""
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        last = await db.scalar(select(YtChat.text).where(YtChat.role == "user").order_by(YtChat.created_at.desc()).limit(1))
    return (texts.detect(last) if last else None) or texts.DEFAULT


# --- what the manager sees ---


async def context(crew: Crew, message: str) -> str:
    studio = await load(crew.engine, crew.tenant_id)
    now = datetime.now(UTC)
    async with AsyncSession(crew.engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, crew.tenant_id)
        b = await credits.balance(db)
        stat = await db.scalar(select(ChannelStat).where(ChannelStat.connection_id == studio.connection_id).order_by(ChannelStat.day.desc()).limit(1))
        videos = await sync.videos_of(db, studio)
        kits = {d.video_id: d.status for d in (await db.scalars(select(YtDraft).where(YtDraft.connection_id == studio.connection_id))).all()}
        applied = set((await db.scalars(select(YtThumbnail.video_id).where(YtThumbnail.connection_id == studio.connection_id,
                                                                            YtThumbnail.status == "applied"))).all())
        latest = {k: await reports.latest(db, studio.connection_id, k) for k in ("pulse", "daily", "review", "ideas")}
        running = (await db.scalars(select(YtReport.kind).where(YtReport.connection_id == studio.connection_id, YtReport.status == "running",
                                                                 YtReport.created_at > now - timedelta(hours=2)))).all()
        waiting = await db.scalar(select(YtReply.reply_id).where(YtReply.connection_id == studio.connection_id, YtReply.status == "new").limit(1))
        new_ideas = len((await db.scalars(select(YtIdea.idea_id).where(YtIdea.connection_id == studio.connection_id, YtIdea.status == "new"))).all())
        history = list(reversed((await db.scalars(select(YtChat).order_by(YtChat.created_at.desc()).limit(HISTORY + 1))).all()))[:-1]
    reply_lang = texts.detect(message) or await _lang(crew.engine, crew.tenant_id)
    dump = reports.dumps
    return (
        f"<reply_language>{reply_lang}</reply_language>\n"
        f"<channel>\n{dump(studio.channel_block())}\n</channel>\n"
        f"<numbers>{dump({'subscribers': stat.followers if stat else None, 'total_views': stat.views if stat else None, 'videos': stat.posts if stat else None, 'as_of': stat.day if stat else None})}</numbers>\n"
        f"<latest_reports>\n{dump({k: {'date': r.created_at, 'headline': (r.output or {}).get('headline') or (r.output or {}).get('summary')} for k, r in latest.items() if r and r.status == 'done'})}\n</latest_reports>\n"
        f"<videos>\n{dump([{'video_id': v.video_id, 'title': v.title, 'published': v.published_at.date() if v.published_at else None, 'views': v.views, 'short': v.is_short, 'kit': kits.get(v.video_id), 'thumbnail_on_youtube': v.video_id in applied} for v in videos[:40]])}\n</videos>\n"
        f"<work_in_progress>{dump({'reports_running': list(running), 'new_comments_waiting': bool(waiting), 'new_ideas': new_ideas})}</work_in_progress>\n"
        f"<credits>{dump({'left': b.total if b.active else 0, 'costs': {'review': credits.COST['review'], 'ideas': credits.COST['ideas'], 'kit': credits.COST['metadata'], 'thumbnails_with_ai_backgrounds': credits.COST['thumbnail_ai'] * 3, 'thumbnails_on_video_frame': 0, 'comments': credits.COST['comments'], 'pulse': 0, 'daily': 0, 'sync': 0}})}</credits>\n"
        f"<conversation>\n" + "\n".join(f"{'owner' if m.role == 'user' else m.agent}: {m.text[:500]}" for m in history) + "\n</conversation>\n"
        f"<message>{message}</message>"
    )


# --- the manager's turn ---


async def handle(crew: Crew, message: str) -> None:
    """Background: the manager answers the owner's message and starts the work it chose."""
    _busy.add(crew.tenant_id)
    try:
        lang = texts.detect(message) or await _lang(crew.engine, crew.tenant_id)
        if crew.llm is None:
            await say(crew.engine, crew.tenant_id, "yt_lead", MSG["no_ai"][lang])
            return
        try:
            turn = (await agents.lead(crew.llm, crew.tenant_id, await context(crew, message))).output
        except LLMError as e:
            await say(crew.engine, crew.tenant_id, "yt_lead", say_text("failed", lang, error=str(e)[:200]))
            return
        await say(crew.engine, crew.tenant_id, "yt_lead", turn.reply)
        for action in turn.actions[:4]:
            await start(crew, action, lang)
    finally:
        _busy.discard(crew.tenant_id)


async def start(crew: Crew, a: agents.LeadAction, lang: str) -> None:
    """Check one action and start it; the team member reports when it is done."""
    who = WHO[a.type]
    try:
        studio = await load(crew.engine, crew.tenant_id)
        if a.type in ("kit", "thumbnails"):
            async with AsyncSession(crew.engine, expire_on_commit=False) as db, db.begin():
                await set_tenant(db, crew.tenant_id)
                video = await db.get(YtVideo, (studio.connection_id, a.video_id or ""))
            if video is None:
                await say(crew.engine, crew.tenant_id, who, MSG["no_video"][lang])
                return
        if a.type == "add_competitors":
            added, missing = await ideas.add_competitors(crew.engine, crew.yt, crew.vault, studio, a.channels or [])
            extra = say_text("missing", lang, list=", ".join(missing)) if missing else ""
            await say(crew.engine, crew.tenant_id, who, say_text("done_rivals", lang, added=", ".join(added) or "—", missing=extra))
            return
        await say(crew.engine, crew.tenant_id, who, say_text("started", lang, who=NAMES[who][lang], what=WHAT[a.type][lang]))
        social_lead.spawn(_work, crew=crew, action=a, lang=lang)
    except (QuotaError, YouTubeError) as e:
        await say(crew.engine, crew.tenant_id, who, say_text("failed", lang, error=str(e)[:300]))


async def _work(*, crew: Crew, action: agents.LeadAction, lang: str) -> None:
    a, e_, t_ = action, crew.engine, crew.tenant_id
    who = WHO[a.type]
    try:
        if a.type == "sync":
            studio = await load(e_, t_)
            n = await sync.sync_videos(e_, crew.yt, crew.vault, studio)
            await stats.collect_tenant(e_, crew.vault, stats.youtube_readers(crew.yt), t_, force=True)
            await say(e_, t_, who, say_text("done_sync", lang, videos=n))
        elif a.type in ("pulse", "daily", "review"):
            studio = await load(e_, t_)
            rid = await reports.create(e_, studio, a.type, cost=credits.COST["review"] if a.type == "review" else 0, by=crew.by)
            if a.type == "review":
                await reports.run_review(engine=e_, llm=crew.llm, yt=crew.yt, vault=crew.vault, http=crew.http, tenant_id=t_, report_id=rid)
            elif a.type == "daily":
                await reports.run_daily(engine=e_, llm=crew.llm, yt=crew.yt, vault=crew.vault, tenant_id=t_, report_id=rid)
            else:
                await reports.run_pulse(engine=e_, llm=crew.llm, yt=crew.yt, vault=crew.vault, tenant_id=t_, report_id=rid,
                                        hours=studio.settings.pulse_hours or 6)
            await _report_done(crew, who, rid, lang)
        elif a.type == "ideas":
            studio = await load(e_, t_)
            rid = await reports.create(e_, studio, "ideas", cost=credits.COST["ideas"], by=crew.by)
            await ideas.run_ideas(engine=e_, llm=crew.llm, yt=crew.yt, vault=crew.vault, tenant_id=t_, report_id=rid)
            async with AsyncSession(e_, expire_on_commit=False) as db, db.begin():
                await set_tenant(db, t_)
                r = await db.get(YtReport, rid)
                n = len((await db.scalars(select(YtIdea.idea_id).where(YtIdea.report_id == rid))).all())
            if r.status == "done":
                await say(e_, t_, who, say_text("done_ideas", lang, n=n), {"link": "ideas", "report_id": str(rid)})
            else:
                await say(e_, t_, who, say_text("failed", lang, error=r.error or ""))
        elif a.type == "kit":
            studio = await load(e_, t_)
            did = await kit.start(e_, t_, studio.connection_id, a.video_id, kit.KitOptions(keywords=(a.notes or "")[:300]), crew.by)
            await kit.run(engine=e_, llm=crew.llm, yt=crew.yt, vault=crew.vault, tenant_id=t_, draft_id=did)
            async with AsyncSession(e_, expire_on_commit=False) as db, db.begin():
                await set_tenant(db, t_)
                d = await db.get(YtDraft, did)
                v = await db.get(YtVideo, (studio.connection_id, a.video_id))
            if d.status == "ready":
                await say(e_, t_, who, say_text("done_kit", lang, title=v.title, score=(d.seo or {}).get("score", "—")),
                          {"link": "video", "video_id": a.video_id, "tab": "kit"})
            else:
                await say(e_, t_, who, say_text("failed", lang, error=d.error or ""))
        elif a.type == "thumbnails":
            await _thumbnails(crew, a, who, lang)
        elif a.type == "comments":
            studio = await load(e_, t_)
            await comments.fetch(e_, crew.yt, crew.vault, studio)
            async with AsyncSession(e_, expire_on_commit=False) as db, db.begin():
                await set_tenant(db, t_)
                ids = list((await db.scalars(select(YtReply.reply_id).where(YtReply.connection_id == studio.connection_id, YtReply.status == "new")
                                             .order_by(YtReply.published_at.desc().nullslast()).limit(comments.BATCH))).all())
            if not ids:
                await say(e_, t_, who, MSG["no_comments"][lang])
                return
            n = await comments.draft(e_, crew.llm, studio, ids, crew.by)
            await say(e_, t_, who, say_text("done_comments", lang, n=n), {"link": "comments"})
    except (QuotaError, YouTubeError, LLMError) as e:
        await say(e_, t_, who, say_text("failed", lang, error=str(e)[:300]))
    except Exception:  # noqa: BLE001 — the owner hears about it instead of silence
        log.exception("youtube team work failed")
        await say(e_, t_, who, say_text("failed", lang, error="—"))


async def _report_done(crew: Crew, who: str, rid: uuid.UUID, lang: str) -> None:
    async with AsyncSession(crew.engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, crew.tenant_id)
        r = await db.get(YtReport, rid)
    if r.status != "done":
        await say(crew.engine, crew.tenant_id, who, say_text("failed", lang, error=r.error or ""))
        return
    from del_social.youtube import i18n

    shown, changed = await i18n.localized(crew.llm, crew.tenant_id, r.output, lang)
    if changed:
        async with AsyncSession(crew.engine) as db, db.begin():
            await set_tenant(db, crew.tenant_id)
            row = await db.get(YtReport, rid)
            row.output = r.output
    await say(crew.engine, crew.tenant_id, who, say_text("done_report", lang, headline=(shown or {}).get("headline", "")),
              {"link": "reports", "report_id": str(rid), "kind": r.kind})


async def _thumbnails(crew: Crew, a: agents.LeadAction, who: str, lang: str) -> None:
    studio = await load(crew.engine, crew.tenant_id)
    ai = bool(a.ai_backgrounds) and crew.fal is not None
    ids = [uuid.uuid4() for _ in range(3)]
    async with AsyncSession(crew.engine) as db, db.begin():
        await set_tenant(db, crew.tenant_id)
        for tid in ids:
            if ai:
                await credits.spend(db, crew.tenant_id, credits.COST["thumbnail_ai"], "thumbnail_ai", tid, crew.by)
            db.add(YtThumbnail(thumbnail_id=tid, tenant_id=crew.tenant_id, connection_id=studio.connection_id, video_id=a.video_id,
                               status="working", spec=render.Spec(language=studio.settings.languages[0]).model_dump(), created_by=crew.by))
    await thumbs.run_design(engine=crew.engine, settings=crew.settings, llm=crew.llm, fal=crew.fal, http=crew.http, tenant_id=crew.tenant_id,
                            video_id=a.video_id, wishes=(a.notes or "")[:600], ai_backgrounds=ai, ids=ids, by=crew.by)
    async with AsyncSession(crew.engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, crew.tenant_id)
        v = await db.get(YtVideo, (studio.connection_id, a.video_id))
    await say(crew.engine, crew.tenant_id, who, say_text("done_thumbs", lang, title=v.title if v else a.video_id),
              {"link": "video", "video_id": a.video_id, "tab": "thumbs"})


# --- who is working now (for the roster) ---


async def roster(db: AsyncSession, connection_id: uuid.UUID) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    recent = now - timedelta(hours=2)
    kinds = set((await db.scalars(select(YtReport.kind).where(YtReport.connection_id == connection_id, YtReport.status == "running",
                                                               YtReport.created_at > recent))).all())
    kit_busy = await db.scalar(select(YtDraft.draft_id).where(YtDraft.connection_id == connection_id, YtDraft.status == "running",
                                                              YtDraft.created_at > recent).limit(1))
    thumb_busy = await db.scalar(select(YtThumbnail.thumbnail_id).where(YtThumbnail.connection_id == connection_id, YtThumbnail.status == "working",
                                                                         YtThumbnail.created_at > recent).limit(1))
    lab_busy = await db.scalar(select(YtJob.job_id).where(YtJob.status.in_(("queued", "running")), YtJob.created_at > now - timedelta(hours=6)).limit(1))
    last = {}
    for agent in ROSTER:
        last[agent] = await db.scalar(select(YtChat.created_at).where(YtChat.agent == agent).order_by(YtChat.created_at.desc()).limit(1))
    busy = {
        "yt_reporter": bool(kinds & {"pulse", "daily"}), "yt_reviewer": "review" in kinds, "yt_ideas": "ideas" in kinds,
        "yt_metadata": bool(kit_busy), "yt_thumbnail": bool(thumb_busy), "yt_replies": False, "yt_editor": bool(lab_busy),
    }
    return [{"agent": a, "working": busy.get(a, False), "last_at": last[a]} for a in ROSTER]


def is_busy(tenant_id: uuid.UUID) -> bool:
    return tenant_id in _busy
