"""YouTube Studio (ADR 012): the channel, reports, ideas, publishing kits, thumbnails and comments.

Every route needs the add-on to be active (the dashboard answers without it, to offer it). Work that
costs credits is paid before it starts (402 when credits are short) and refunded if it fails.
Anything that changes the channel on YouTube is an explicit action by a person.
"""
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from del_social.billing import credits
from del_social.connections import stats
from del_social.connections.youtube import YouTubeClient, YouTubeError
from del_social.core.config import get_settings
from del_social.core.db import set_tenant
from del_social.core.deps import (
    TenantContext,
    get_db,
    get_engine,
    get_http,
    get_redis,
    get_vault,
    get_vault_optional,
    get_youtube,
    get_youtube_optional,
    require_permission,
)
from del_social.core.vault import TokenVault
from del_social.llm import LLM
from del_social.media import images
from del_social.media.fal import FalClient
from del_social.models import ChannelStat, YtChat, YtCompetitor, YtDraft, YtIdea, YtReply, YtReport, YtThumbnail, YtVideo
from del_social.routes.media import get_analyst, get_fal
from del_social.team import lead
from del_social.tenants.permissions import Permission
from del_social.youtube import channel, comments, i18n, ideas, kit, render, reports, sync, team, thumbs
from del_social.youtube.channel import Settings, Studio

router = APIRouter(prefix="/tenants/{tenant_id}/youtube", tags=["youtube"])

can_view = require_permission(Permission.VIEW)
can_work = require_permission(Permission.APPROVE_CONTENT)  # make kits, thumbnails, replies; send them to YouTube
can_manage = require_permission(Permission.MANAGE_BRAND)  # channel settings and competitors


async def studio_of(ctx: TenantContext, db: AsyncSession) -> Studio:
    await credits.require_addon(db)
    conn = await channel.youtube_connection(db)
    if conn is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect a YouTube channel first (Settings → Connections)")
    return Studio(ctx.tenant_id, conn, await channel.settings_of(db, conn.connection_id))


def need_llm(llm: LLM | None) -> LLM:
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The AI team is not configured on this server")
    return llm


def need_fal(fal: FalClient | None) -> FalClient:
    if fal is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI images are not configured on this server")
    return fal


async def once(redis: Redis, key: str, seconds: int, message: str) -> None:
    if not await redis.set(key, "1", nx=True, ex=seconds):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message)


async def _localize_reports(llm: LLM | None, tenant_id: uuid.UUID, rows: list[YtReport], lang: str | None) -> dict[uuid.UUID, Any]:
    """Each report's output in the reader's language (translated once, then cached on the row)."""
    results = await i18n.localize_many(llm, tenant_id, [r.output for r in rows], lang)
    shown = {}
    for r, (out, changed) in zip(rows, results):
        if changed:
            flag_modified(r, "output")  # the cached translation was added inside the JSON value
        shown[r.report_id] = out
    return shown


def _report(r: YtReport, output: Any = None) -> dict[str, Any]:
    return {"report_id": r.report_id, "kind": r.kind, "status": r.status, "output": output if output is not None else r.output, "input": r.input,
            "sources": r.sources, "credits": r.credits, "error": r.error, "created_at": r.created_at, "finished_at": r.finished_at}


def _video(v: YtVideo) -> dict[str, Any]:
    return {k: getattr(v, k) for k in ("video_id", "title", "description", "tags", "published_at", "duration_s", "privacy",
                                       "publish_at", "is_short", "thumbnail_url", "views", "likes", "comments", "has_captions")}


def _thumb(t: YtThumbnail, tenant_id: uuid.UUID) -> dict[str, Any]:
    return {"thumbnail_id": t.thumbnail_id, "video_id": t.video_id, "status": t.status, "spec": t.spec, "background": t.background,
            "error": t.error, "applied_at": t.applied_at, "created_at": t.created_at, "rev": t.rev,
            "image": f"/tenants/{tenant_id}/youtube/thumbnails/{t.thumbnail_id}/image?rev={t.rev}"}


# --- dashboard and settings ---


@router.get("")
async def dashboard(lang: str | None = None, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db),
                    yt: YouTubeClient | None = Depends(get_youtube_optional), llm: LLM | None = Depends(get_analyst)) -> dict[str, Any]:
    b = await credits.balance(db)
    out: dict[str, Any] = {
        "addon": {"active": b.active, "total": b.total if b.active else 0, "monthly_left": b.monthly_left, "purchased": max(0, b.purchased),
                  "period_end": b.period_end, "costs": credits.COST},
        "google_configured": yt is not None, "connection": None,
    }
    conn = await channel.youtube_connection(db)
    if conn is None:
        return out
    rows = list((await db.scalars(select(ChannelStat).where(ChannelStat.connection_id == conn.connection_id)
                                  .order_by(ChannelStat.day.desc()).limit(40))).all())
    last = rows[0] if rows else None
    out["connection"] = {"connection_id": conn.connection_id, "name": conn.display_name, "status": conn.status,
                         "last_error": conn.last_error, **{k: (conn.details or {}).get(k) for k in ("handle", "avatar", "country")}}
    out["channel"] = {"subscribers": last.followers if last else None, "views": last.views if last else None,
                      "videos": last.posts if last else None, "growth_7d": stats.growth(rows, 7), "growth_30d": stats.growth(rows, 30),
                      "series": [{"day": r.day, "subscribers": r.followers, "views": r.views} for r in reversed(rows)]}
    out["settings"] = (await channel.settings_of(db, conn.connection_id)).model_dump()
    found = {kind: await reports.latest(db, conn.connection_id, kind) for kind in ("pulse", "daily", "review", "ideas")}
    rows = [r for r in found.values() if r is not None]
    shown = await _localize_reports(llm, ctx.tenant_id, rows, lang)
    out["latest"] = {kind: _report(r, shown.get(r.report_id)) if r else None for kind, r in found.items()}
    out["counts"] = {
        "videos": await db.scalar(select(func.count()).where(YtVideo.connection_id == conn.connection_id)) or 0,
        "replies_waiting": await db.scalar(select(func.count()).where(YtReply.connection_id == conn.connection_id,
                                                                     YtReply.status.in_(("new", "drafted")))) or 0,
        "ideas_new": await db.scalar(select(func.count()).where(YtIdea.connection_id == conn.connection_id, YtIdea.status == "new")) or 0,
    }
    return out


@router.put("/settings")
async def save_settings(body: Settings, ctx: TenantContext = Depends(can_manage), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    st = await studio_of(ctx, db)
    return (await channel.save_settings(db, ctx.tenant_id, st.connection_id, body)).model_dump()


@router.post("/sync")
async def sync_now(ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db), engine: AsyncEngine = Depends(get_engine),
                   yt: YouTubeClient = Depends(get_youtube), vault: TokenVault = Depends(get_vault),
                   redis: Redis = Depends(get_redis)) -> dict[str, int]:
    st = await studio_of(ctx, db)
    await once(redis, f"yt:sync:{st.connection_id}", 120, "Synced a moment ago; try again in two minutes")
    try:
        n = await sync.sync_videos(engine, yt, vault, st)
        await stats.collect_tenant(engine, vault, stats.youtube_readers(yt), ctx.tenant_id, force=True)
    except YouTubeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    return {"videos": n}


# --- videos ---


@router.get("/videos")
async def list_videos(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    st = await studio_of(ctx, db)
    drafts = {d.video_id: d for d in (await db.scalars(select(YtDraft).where(YtDraft.connection_id == st.connection_id)
                                                        .order_by(YtDraft.created_at))).all()}
    applied = set((await db.scalars(select(YtThumbnail.video_id).where(YtThumbnail.connection_id == st.connection_id,
                                                                        YtThumbnail.status == "applied"))).all())
    return [_video(v) | {"kit": drafts[v.video_id].status if v.video_id in drafts else None, "thumbnail_applied": v.video_id in applied}
            for v in await sync.videos_of(db, st)]


@router.get("/videos/{video_id}")
async def video_detail(video_id: str, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    st = await studio_of(ctx, db)
    v = await db.get(YtVideo, (st.connection_id, video_id))
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    drafts = (await db.scalars(select(YtDraft).where(YtDraft.connection_id == st.connection_id, YtDraft.video_id == video_id)
                               .order_by(YtDraft.created_at.desc()).limit(5))).all()
    thumbs_ = (await db.scalars(select(YtThumbnail).where(YtThumbnail.connection_id == st.connection_id, YtThumbnail.video_id == video_id)
                                .order_by(YtThumbnail.created_at.desc()).limit(24))).all()
    return {"video": _video(v), "drafts": [_draft(d) for d in drafts], "thumbnails": [_thumb(t, ctx.tenant_id) for t in thumbs_]}


def _draft(d: YtDraft) -> dict[str, Any]:
    return {k: getattr(d, k) for k in ("draft_id", "video_id", "status", "options", "output", "chosen", "seo", "error", "applied_at", "created_at")}


# --- reports ---


@router.get("/reports")
async def list_reports(kind: str | None = None, lang: str | None = None, ctx: TenantContext = Depends(can_view),
                       db: AsyncSession = Depends(get_db), llm: LLM | None = Depends(get_analyst)) -> list[dict[str, Any]]:
    st = await studio_of(ctx, db)
    q = select(YtReport).where(YtReport.connection_id == st.connection_id)
    if kind:
        q = q.where(YtReport.kind == kind)
    rows = list((await db.scalars(q.order_by(YtReport.created_at.desc()).limit(40))).all())
    shown = await _localize_reports(llm, ctx.tenant_id, rows[:8], lang)  # the newest ones; older ones on the next views
    return [_report(r, shown.get(r.report_id)) for r in rows]


@router.post("/reports/{kind}", status_code=status.HTTP_202_ACCEPTED)
async def run_report(kind: Literal["pulse", "daily", "review"], ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db),
                     engine: AsyncEngine = Depends(get_engine), yt: YouTubeClient = Depends(get_youtube),
                     vault: TokenVault = Depends(get_vault), llm: LLM | None = Depends(get_analyst),
                     http: httpx.AsyncClient = Depends(get_http), redis: Redis = Depends(get_redis)) -> dict[str, Any]:
    st = await studio_of(ctx, db)
    llm = need_llm(llm)
    if kind != "review":
        await once(redis, f"yt:{kind}:{st.connection_id}", 1800, "This report was made less than 30 minutes ago")
    rid = await reports.create(engine, st, kind, cost=credits.COST["review"] if kind == "review" else 0, by=ctx.account.account_id)
    if kind == "review":
        lead.spawn(reports.run_review, engine=engine, llm=llm, yt=yt, vault=vault, http=http, tenant_id=ctx.tenant_id, report_id=rid)
    elif kind == "daily":
        lead.spawn(reports.run_daily, engine=engine, llm=llm, yt=yt, vault=vault, tenant_id=ctx.tenant_id, report_id=rid)
    else:
        lead.spawn(reports.run_pulse, engine=engine, llm=llm, yt=yt, vault=vault, tenant_id=ctx.tenant_id, report_id=rid,
                   hours=st.settings.pulse_hours or 6)
    return {"report_id": rid}


# --- ideas and competitors ---


@router.post("/ideas/run", status_code=status.HTTP_202_ACCEPTED)
async def run_ideas(ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db), engine: AsyncEngine = Depends(get_engine),
                    yt: YouTubeClient = Depends(get_youtube), vault: TokenVault = Depends(get_vault),
                    llm: LLM | None = Depends(get_analyst)) -> dict[str, Any]:
    st = await studio_of(ctx, db)
    llm = need_llm(llm)
    rid = await reports.create(engine, st, "ideas", cost=credits.COST["ideas"], by=ctx.account.account_id)
    lead.spawn(ideas.run_ideas, engine=engine, llm=llm, yt=yt, vault=vault, tenant_id=ctx.tenant_id, report_id=rid)
    return {"report_id": rid}


@router.get("/ideas")
async def list_ideas(lang: str | None = None, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db),
                     llm: LLM | None = Depends(get_analyst)) -> list[dict[str, Any]]:
    st = await studio_of(ctx, db)
    rows = list((await db.scalars(select(YtIdea).where(YtIdea.connection_id == st.connection_id, YtIdea.status != "dismissed")
                                  .order_by(YtIdea.created_at.desc()).limit(60))).all())
    results = await i18n.localize_many(llm, ctx.tenant_id, [i.data for i in rows], lang)
    out = []
    for i, (data, changed) in zip(rows, results):
        if changed:
            flag_modified(i, "data")
        out.append({"idea_id": i.idea_id, "title": i.title, "status": i.status, "created_at": i.created_at,
                    **{k: v for k, v in (data or {}).items() if k != "_i18n"}})
    return out


class IdeaStatus(BaseModel):
    status: Literal["new", "saved", "used", "dismissed"]


@router.patch("/ideas/{idea_id}")
async def set_idea(idea_id: uuid.UUID, body: IdeaStatus, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    i = await db.get(YtIdea, idea_id)
    if i is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Idea not found")
    i.status = body.status
    return {"status": i.status}


@router.get("/competitors")
async def list_competitors(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    st = await studio_of(ctx, db)
    rows = (await db.scalars(select(YtCompetitor).where(YtCompetitor.connection_id == st.connection_id).order_by(YtCompetitor.created_at))).all()
    return [{k: getattr(r, k) for k in ("competitor_id", "channel_id", "handle", "title", "subscribers", "videos", "views", "avatar",
                                        "source", "status", "checked_at")} for r in rows]


class CompetitorsIn(BaseModel):
    channels: list[str] = Field(min_length=1, max_length=10)


@router.post("/competitors")
async def add_competitors(body: CompetitorsIn, ctx: TenantContext = Depends(can_manage), db: AsyncSession = Depends(get_db),
                          engine: AsyncEngine = Depends(get_engine), yt: YouTubeClient = Depends(get_youtube),
                          vault: TokenVault = Depends(get_vault)) -> dict[str, list[str]]:
    st = await studio_of(ctx, db)
    have = await db.scalar(select(func.count()).where(YtCompetitor.connection_id == st.connection_id)) or 0
    if have + len(body.channels) > ideas.MAX_COMPETITORS:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Up to {ideas.MAX_COMPETITORS} channels can be watched")
    try:
        added, missing = await ideas.add_competitors(engine, yt, vault, st, [c[:200] for c in body.channels])
    except YouTubeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    return {"added": added, "not_found": missing}


@router.delete("/competitors/{competitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_competitor(competitor_id: uuid.UUID, ctx: TenantContext = Depends(can_manage), db: AsyncSession = Depends(get_db)) -> None:
    r = await db.get(YtCompetitor, competitor_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await db.delete(r)


# --- publishing kit ---


@router.post("/videos/{video_id}/kit", status_code=status.HTTP_202_ACCEPTED)
async def make_kit(video_id: str, body: kit.KitOptions, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db),
                   engine: AsyncEngine = Depends(get_engine), yt: YouTubeClient = Depends(get_youtube),
                   vault: TokenVault = Depends(get_vault), llm: LLM | None = Depends(get_analyst)) -> dict[str, Any]:
    st = await studio_of(ctx, db)
    llm = need_llm(llm)
    if await db.get(YtVideo, (st.connection_id, video_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found (sync the channel)")
    did = await kit.start(engine, ctx.tenant_id, st.connection_id, video_id, body, ctx.account.account_id)
    lead.spawn(kit.run, engine=engine, llm=llm, yt=yt, vault=vault, tenant_id=ctx.tenant_id, draft_id=did)
    return {"draft_id": did}


@router.get("/drafts/{draft_id}")
async def get_draft(draft_id: uuid.UUID, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    d = await db.get(YtDraft, draft_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return _draft(d)


@router.post("/drafts/{draft_id}/apply")
async def apply_draft(draft_id: uuid.UUID, body: kit.Chosen, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db),
                      engine: AsyncEngine = Depends(get_engine), yt: YouTubeClient = Depends(get_youtube),
                      vault: TokenVault = Depends(get_vault)) -> dict[str, Any]:
    await studio_of(ctx, db)
    d = await db.get(YtDraft, draft_id)
    if d is None or d.status not in ("ready", "applied"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This kit is not ready")
    try:
        return await kit.apply(engine, yt, vault, ctx.tenant_id, draft_id, body)
    except (YouTubeError, ValueError) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None


@router.get("/playlists")
async def playlists(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db), yt: YouTubeClient = Depends(get_youtube),
                    vault: TokenVault = Depends(get_vault)) -> list[dict[str, str]]:
    st = await studio_of(ctx, db)
    try:
        items = await yt.playlists(channel.creds(vault, st))
    except YouTubeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    return [{"playlist_id": p["id"], "title": (p.get("snippet") or {}).get("title", "")} for p in items]


# --- thumbnails ---


class DesignIn(BaseModel):
    wishes: str = Field(default="", max_length=600)
    ai_backgrounds: bool = False  # 2 credits per concept; otherwise the video's own frame


@router.post("/videos/{video_id}/thumbnails/design", status_code=status.HTTP_202_ACCEPTED)
async def design_thumbnails(video_id: str, body: DesignIn, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db),
                            engine: AsyncEngine = Depends(get_engine), llm: LLM | None = Depends(get_analyst),
                            fal: FalClient | None = Depends(get_fal), http: httpx.AsyncClient = Depends(get_http)) -> dict[str, Any]:
    st = await studio_of(ctx, db)
    llm = need_llm(llm)
    if body.ai_backgrounds:
        need_fal(fal)
    ids = [uuid.uuid4() for _ in range(3)]
    async with AsyncSession(engine) as own, own.begin():
        await set_tenant(own, ctx.tenant_id)
        for tid in ids:
            if body.ai_backgrounds:
                await credits.spend(own, ctx.tenant_id, credits.COST["thumbnail_ai"], "thumbnail_ai", tid, ctx.account.account_id)
            own.add(YtThumbnail(thumbnail_id=tid, tenant_id=ctx.tenant_id, connection_id=st.connection_id, video_id=video_id,
                                status="working", spec=render.Spec(language=st.settings.languages[0]).model_dump(),
                                created_by=ctx.account.account_id))
    lead.spawn(thumbs.run_design, engine=engine, settings=get_settings(), llm=llm, fal=fal, http=http, tenant_id=ctx.tenant_id,
               video_id=video_id, wishes=body.wishes, ai_backgrounds=body.ai_backgrounds, ids=ids, by=ctx.account.account_id)
    return {"thumbnail_ids": ids}


class NewThumb(BaseModel):
    video_id: str | None = Field(default=None, max_length=32)
    spec: render.Spec = Field(default_factory=render.Spec)


@router.post("/thumbnails", status_code=status.HTTP_201_CREATED)
async def new_thumbnail(body: NewThumb, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db),
                        engine: AsyncEngine = Depends(get_engine), http: httpx.AsyncClient = Depends(get_http)) -> dict[str, Any]:
    """A blank design on the video's current thumbnail (free)."""
    st = await studio_of(ctx, db)
    frame = await thumbs.youtube_frame(http, body.video_id) if body.video_id else None
    tid = await thumbs.create(engine, get_settings().media_root, st, body.video_id, body.spec, frame,
                              {"source": "youtube" if frame else "palette"}, ctx.account.account_id)
    return {"thumbnail_id": tid}


@router.get("/thumbnails")
async def list_thumbnails(video_id: str | None = None, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    st = await studio_of(ctx, db)
    q = select(YtThumbnail).where(YtThumbnail.connection_id == st.connection_id)
    if video_id:
        q = q.where(YtThumbnail.video_id == video_id)
    return [_thumb(t, ctx.tenant_id) for t in (await db.scalars(q.order_by(YtThumbnail.created_at.desc()).limit(60))).all()]


async def _pay_and_mark(engine: AsyncEngine, ctx: TenantContext, tid: uuid.UUID, work: str) -> tuple[uuid.UUID, dict[str, Any]]:
    """Spend the credits and mark the design as working, committed before the job starts (no race with it)."""
    ref = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as own, own.begin():
        await set_tenant(own, ctx.tenant_id)
        await credits.spend(own, ctx.tenant_id, credits.COST[work], work, ref, ctx.account.account_id)
        t = await own.get(YtThumbnail, tid)
        t.status, t.error = "working", None
    return ref, _thumb(t, ctx.tenant_id)


async def _thumb_row(db: AsyncSession, tid: uuid.UUID) -> YtThumbnail:
    t = await db.get(YtThumbnail, tid)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Thumbnail not found")
    return t


@router.get("/thumbnails/{thumbnail_id}/image")
async def thumbnail_image(thumbnail_id: uuid.UUID, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> Response:
    t = await _thumb_row(db, thumbnail_id)  # RLS: this company's only
    path = thumbs.folder(get_settings().media_root, ctx.tenant_id, t.thumbnail_id) / "render.jpg"
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not rendered yet")
    return Response(path.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.put("/thumbnails/{thumbnail_id}")
async def edit_thumbnail(thumbnail_id: uuid.UUID, spec: render.Spec, ctx: TenantContext = Depends(can_work),
                         db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    t = await _thumb_row(db, thumbnail_id)
    if t.status == "working":
        raise HTTPException(status.HTTP_409_CONFLICT, "This design is still being made")
    t.spec, t.rev = spec.model_dump(), t.rev + 1
    if t.status == "applied":
        t.status = "ready"
    await db.flush()
    thumbs.rerender(get_settings().media_root, t)
    return _thumb(t, ctx.tenant_id)


class BackgroundIn(BaseModel):
    mode: Literal["ai", "edit", "youtube", "palette"]
    prompt: str = Field(default="", max_length=600)


@router.post("/thumbnails/{thumbnail_id}/background", status_code=status.HTTP_202_ACCEPTED)
async def change_background(thumbnail_id: uuid.UUID, body: BackgroundIn, ctx: TenantContext = Depends(can_work),
                            db: AsyncSession = Depends(get_db), engine: AsyncEngine = Depends(get_engine),
                            fal: FalClient | None = Depends(get_fal), http: httpx.AsyncClient = Depends(get_http)) -> dict[str, Any]:
    await studio_of(ctx, db)
    t = await _thumb_row(db, thumbnail_id)
    root = get_settings().media_root
    d = thumbs.folder(root, ctx.tenant_id, thumbnail_id)
    if body.mode in ("youtube", "palette"):
        if body.mode == "youtube":
            frame = await thumbs.youtube_frame(http, t.video_id) if t.video_id else None
            if frame is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "This video has no thumbnail on YouTube yet")
            thumbs._save(d / "background.jpg", thumbs.as_jpeg(frame))
        else:
            (d / "background.jpg").unlink(missing_ok=True)
        t.background, t.rev, t.error = {"source": body.mode}, t.rev + 1, None
        await db.flush()
        thumbs.rerender(root, t)
        return _thumb(t, ctx.tenant_id)
    fal = need_fal(fal)
    if not body.prompt.strip():
        raise HTTPException(422, "Describe the background you want")
    ref, out = await _pay_and_mark(engine, ctx, thumbnail_id, "thumbnail_ai" if body.mode == "ai" else "thumbnail_edit")
    lead.spawn(thumbs.run_background, engine=engine, settings=get_settings(), fal=fal, tenant_id=ctx.tenant_id,
               thumbnail_id=thumbnail_id, mode=body.mode, prompt=body.prompt, ref=ref)
    return out


@router.post("/thumbnails/{thumbnail_id}/upload")
async def upload_layer(thumbnail_id: uuid.UUID, layer: Literal["background", "subject"] = Query("background"),
                       file: UploadFile = File(...), ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db),
                       engine: AsyncEngine = Depends(get_engine), fal: FalClient | None = Depends(get_fal)) -> dict[str, Any]:
    """Upload a background photo (free), or a photo of the subject to cut out (1 credit)."""
    await studio_of(ctx, db)
    t = await _thumb_row(db, thumbnail_id)
    data = await file.read(images.MAX_UPLOAD_BYTES + 1)
    try:
        jpeg = thumbs.as_jpeg(data)
    except images.ImageRejected as e:
        raise HTTPException(422, str(e)) from None
    root = get_settings().media_root
    if layer == "background":
        thumbs._save(thumbs.folder(root, ctx.tenant_id, thumbnail_id) / "background.jpg", jpeg)
        t.background, t.rev, t.error = {"source": "upload"}, t.rev + 1, None
        await db.flush()
        thumbs.rerender(root, t)
        return _thumb(t, ctx.tenant_id)
    fal = need_fal(fal)
    ref, out = await _pay_and_mark(engine, ctx, thumbnail_id, "cutout")
    lead.spawn(thumbs.run_cutout, engine=engine, settings=get_settings(), fal=fal, tenant_id=ctx.tenant_id,
               thumbnail_id=thumbnail_id, source=jpeg, ref=ref)
    return out


@router.post("/thumbnails/{thumbnail_id}/cutout", status_code=status.HTTP_202_ACCEPTED)
async def cutout_background(thumbnail_id: uuid.UUID, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db),
                            engine: AsyncEngine = Depends(get_engine), fal: FalClient | None = Depends(get_fal)) -> dict[str, Any]:
    """Cut the subject out of the current background (1 credit)."""
    await studio_of(ctx, db)
    t = await _thumb_row(db, thumbnail_id)
    fal = need_fal(fal)
    path = thumbs.folder(get_settings().media_root, ctx.tenant_id, thumbnail_id) / "background.jpg"
    if not path.exists():
        raise HTTPException(status.HTTP_409_CONFLICT, "There is no photo to cut out yet")
    ref, out = await _pay_and_mark(engine, ctx, t.thumbnail_id, "cutout")
    lead.spawn(thumbs.run_cutout, engine=engine, settings=get_settings(), fal=fal, tenant_id=ctx.tenant_id,
               thumbnail_id=thumbnail_id, source=path.read_bytes(), ref=ref)
    return out


class ApplyThumb(BaseModel):
    video_id: str = Field(min_length=1, max_length=32)


@router.post("/thumbnails/{thumbnail_id}/apply")
async def apply_thumbnail(thumbnail_id: uuid.UUID, body: ApplyThumb, ctx: TenantContext = Depends(can_work),
                          db: AsyncSession = Depends(get_db), engine: AsyncEngine = Depends(get_engine),
                          yt: YouTubeClient = Depends(get_youtube), vault: TokenVault = Depends(get_vault)) -> dict[str, Any]:
    st = await studio_of(ctx, db)
    await _thumb_row(db, thumbnail_id)
    if await db.get(YtVideo, (st.connection_id, body.video_id)) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    try:
        await thumbs.apply(engine, yt, vault, get_settings().media_root, ctx.tenant_id, thumbnail_id, body.video_id)
    except YouTubeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None
    return {"applied": True, "at": datetime.now(UTC)}


@router.delete("/thumbnails/{thumbnail_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thumbnail(thumbnail_id: uuid.UUID, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db)) -> None:
    t = await _thumb_row(db, thumbnail_id)
    await db.delete(t)
    thumbs.delete_files(get_settings().media_root, ctx.tenant_id, thumbnail_id)


# --- comments ---


@router.get("/comments")
async def list_comments(state: Literal["open", "sent", "dismissed"] = "open", ctx: TenantContext = Depends(can_view),
                        db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    st = await studio_of(ctx, db)
    statuses = {"open": ("new", "drafted"), "sent": ("sent",), "dismissed": ("dismissed",)}[state]
    rows = (await db.scalars(select(YtReply).where(YtReply.connection_id == st.connection_id, YtReply.status.in_(statuses))
                             .order_by(YtReply.published_at.desc().nullslast()).limit(100))).all()
    titles = {v.video_id: v.title for v in await sync.videos_of(db, st)}
    return [{k: getattr(r, k) for k in ("reply_id", "comment_id", "video_id", "author", "text", "published_at", "draft", "status", "sent_at")}
            | {"video_title": titles.get(r.video_id or "", "")} for r in rows]


@router.post("/comments/refresh")
async def refresh_comments(ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db), engine: AsyncEngine = Depends(get_engine),
                           yt: YouTubeClient = Depends(get_youtube), vault: TokenVault = Depends(get_vault),
                           redis: Redis = Depends(get_redis)) -> dict[str, int]:
    st = await studio_of(ctx, db)
    await once(redis, f"yt:comments:{st.connection_id}", 120, "Checked a moment ago; try again in two minutes")
    try:
        return {"added": await comments.fetch(engine, yt, vault, st)}
    except YouTubeError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None


class DraftIn(BaseModel):
    reply_ids: list[uuid.UUID] = Field(min_length=1, max_length=comments.BATCH)


@router.post("/comments/draft")
async def draft_replies(body: DraftIn, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db),
                        engine: AsyncEngine = Depends(get_engine), llm: LLM | None = Depends(get_analyst)) -> dict[str, int]:
    st = await studio_of(ctx, db)
    return {"drafted": await comments.draft(engine, need_llm(llm), st, body.reply_ids, ctx.account.account_id)}


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=1500)


@router.post("/comments/{reply_id}/send")
async def send_reply(reply_id: uuid.UUID, body: SendIn, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db),
                     engine: AsyncEngine = Depends(get_engine), yt: YouTubeClient = Depends(get_youtube),
                     vault: TokenVault = Depends(get_vault)) -> dict[str, str]:
    await studio_of(ctx, db)
    r = await db.get(YtReply, reply_id)
    if r is None or r.status == "sent":
        raise HTTPException(status.HTTP_409_CONFLICT, "Already answered or not found")
    try:
        await comments.send(engine, yt, vault, ctx.tenant_id, reply_id, body.text)
    except YouTubeError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from None
    return {"status": "sent"}


@router.post("/comments/{reply_id}/dismiss")
async def dismiss_reply(reply_id: uuid.UUID, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db)) -> dict[str, str]:
    r = await db.get(YtReply, reply_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    r.status = "dismissed"
    return {"status": r.status}


# --- the team: chat with the Channel Manager ---


@router.get("/team")
async def team_room(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    st = await studio_of(ctx, db)
    rows = list(reversed((await db.scalars(select(YtChat).order_by(YtChat.created_at.desc()).limit(80))).all()))
    return {
        "messages": [{k: getattr(m, k) for k in ("message_id", "role", "agent", "text", "payload", "created_at")} for m in rows],
        "roster": await team.roster(db, st.connection_id),
        "lead_busy": team.is_busy(ctx.tenant_id),
    }


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/team/chat", status_code=status.HTTP_202_ACCEPTED)
async def team_chat(body: ChatIn, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db),
                    engine: AsyncEngine = Depends(get_engine), llm: LLM | None = Depends(get_analyst),
                    yt: YouTubeClient | None = Depends(get_youtube_optional), vault: TokenVault | None = Depends(get_vault_optional),
                    http: httpx.AsyncClient = Depends(get_http), fal: FalClient | None = Depends(get_fal)) -> dict[str, str]:
    await studio_of(ctx, db)
    if team.is_busy(ctx.tenant_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "The manager is still answering the last message")
    async with AsyncSession(engine) as own, own.begin():  # committed before the manager reads the conversation
        await set_tenant(own, ctx.tenant_id)
        own.add(YtChat(message_id=uuid.uuid4(), tenant_id=ctx.tenant_id, role="user", text=body.text.strip(), author=ctx.account.account_id))
    crew = team.Crew(engine=engine, settings=get_settings(), tenant_id=ctx.tenant_id, llm=llm, yt=yt, vault=vault, http=http, fal=fal,
                     by=ctx.account.account_id)
    team._busy.add(ctx.tenant_id)  # busy from now, so a quick second message waits
    lead.spawn(team.handle, crew=crew, message=body.text.strip())
    return {"status": "thinking"}
