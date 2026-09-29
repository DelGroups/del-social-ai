"""Video lab (ADR 012): chunked uploads, the media library, jobs, AI video, and signed links for fal.ai."""
import json
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.billing import credits
from del_social.connections.youtube import YouTubeClient
from del_social.core.config import get_settings
from del_social.core.db import set_tenant
from del_social.core.deps import (
    TenantContext,
    get_db,
    get_engine,
    get_http,
    get_vault_optional,
    get_youtube_optional,
    require_permission,
)
from del_social.core.vault import TokenVault
from del_social.llm import LLM
from del_social.media import images
from del_social.media.fal import FalClient
from del_social.media.storage import MediaNotConfigured
from del_social.models import YtJob, YtMedia
from del_social.routes.media import get_analyst, get_fal
from del_social.team import lead
from del_social.tenants.permissions import Permission
from del_social.youtube.lab import ffmpeg, files, jobs, models

router = APIRouter(prefix="/tenants/{tenant_id}/youtube/lab", tags=["youtube-lab"])
public_router = APIRouter(tags=["youtube-lab"])

can_view = require_permission(Permission.VIEW)
can_work = require_permission(Permission.APPROVE_CONTENT)
MAX_DURATION_S = 90 * 60


def get_video_fal(http: httpx.AsyncClient = Depends(get_http)) -> FalClient | None:
    s = get_settings()
    return FalClient(http, s.fal_key, 5.0, s.video_timeout_seconds) if s.fal_key else None


def get_lab(ctx: TenantContext = Depends(can_view), engine: AsyncEngine = Depends(get_engine), llm: LLM | None = Depends(get_analyst),
            fal: FalClient | None = Depends(get_fal), video_fal: FalClient | None = Depends(get_video_fal),
            yt: YouTubeClient | None = Depends(get_youtube_optional), vault: TokenVault | None = Depends(get_vault_optional),
            http: httpx.AsyncClient = Depends(get_http)) -> jobs.Lab:
    return jobs.Lab(engine=engine, settings=get_settings(), tenant_id=ctx.tenant_id, llm=llm, fal=fal, video_fal=video_fal, yt=yt,
                    vault=vault, http=http)


def _media(m: YtMedia, tenant_id: uuid.UUID, with_transcript: bool = False) -> dict[str, Any]:
    out = {k: getattr(m, k) for k in ("media_id", "kind", "status", "title", "filename", "bytes", "expected_bytes", "duration_s", "width",
                                      "height", "has_audio", "source_media_id", "youtube_video_id", "error", "created_at", "expires_at")}
    out["has_transcript"] = bool((m.transcript or {}).get("segments"))
    out["video"] = f"/tenants/{tenant_id}/youtube/lab/media/{m.media_id}/video" if m.status == "ready" else None
    if with_transcript:
        out["transcript"] = m.transcript
    return out


def _job(j: YtJob) -> dict[str, Any]:
    return {k: getattr(j, k) for k in ("job_id", "media_id", "kind", "status", "progress", "options", "result", "credits", "error",
                                       "created_at", "finished_at")}


@router.get("")
async def lab_home(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await credits.require_addon(db)
    media = (await db.scalars(select(YtMedia).order_by(YtMedia.created_at.desc()).limit(80))).all()
    return {
        "media": [_media(m, ctx.tenant_id) for m in media],
        "jobs": [_job(j) for j in await jobs.latest_jobs(db)],
        "models": [{k: getattr(m, k) for k in ("key", "name", "tier", "durations", "aspects", "credits_per_second", "audio")}
                   | {"image": m.image_model is not None} for m in models.catalog()],
        "usage_bytes": files.usage(get_settings().media_root, ctx.tenant_id),
        "limits": {"upload_bytes": files.MAX_UPLOAD, "space_bytes": files.MAX_TENANT_BYTES, "chunk_bytes": 8 * 1024 * 1024,
                   "duration_s": MAX_DURATION_S},
    }


class UploadStart(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    size: int = Field(gt=0)


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def upload_start(body: UploadStart, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db),
                       engine: AsyncEngine = Depends(get_engine)) -> dict[str, Any]:
    await credits.require_addon(db)
    try:
        files.source_name(body.filename)
    except files.LabError as e:
        raise HTTPException(422, str(e)) from None
    if body.size > files.MAX_UPLOAD:
        raise HTTPException(413, "Videos up to 4 GB can be uploaded")
    if files.usage(get_settings().media_root, ctx.tenant_id) + body.size > files.MAX_TENANT_BYTES:
        raise HTTPException(413, "The lab is full: delete old videos first (they are also removed after 14 days)")
    mid = await jobs.new_media(engine, ctx.tenant_id, "upload", files.clean_title(body.filename), None, ctx.account.account_id,
                               filename=body.filename, expected=body.size)
    return {"media_id": mid}


async def _upload_row(db: AsyncSession, media_id: uuid.UUID) -> YtMedia:
    m = await db.get(YtMedia, media_id)
    if m is None or m.kind != "upload":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Upload not found")
    if m.status != "uploading":
        raise HTTPException(status.HTTP_409_CONFLICT, "This upload is finished")
    return m


@router.put("/uploads/{media_id}")
async def upload_chunk(media_id: uuid.UUID, request: Request, offset: int = Query(ge=0), ctx: TenantContext = Depends(can_work),
                       db: AsyncSession = Depends(get_db)) -> dict[str, int]:
    m = await _upload_row(db, media_id)
    data = await request.body()
    path = files.folder(get_settings().media_root, ctx.tenant_id, media_id) / files.source_name(m.filename)
    try:
        size = files.append(path, offset, data)
    except files.LabError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    if m.expected_bytes and size > m.expected_bytes:
        raise HTTPException(413, "More data than announced")
    m.bytes = size
    return {"bytes": size}


@router.post("/uploads/{media_id}/complete")
async def upload_complete(media_id: uuid.UUID, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db),
                          lab: jobs.Lab = Depends(get_lab)) -> dict[str, Any]:
    m = await _upload_row(db, media_id)
    path = files.folder(get_settings().media_root, ctx.tenant_id, media_id) / files.source_name(m.filename)
    try:
        p = await ffmpeg.probe(path)
        if p.duration > MAX_DURATION_S:
            raise ffmpeg.FFmpegError("Videos up to 90 minutes can be used in the lab")
    except ffmpeg.FFmpegError as e:
        m.status, m.error = "failed", str(e)
        files.remove(get_settings().media_root, ctx.tenant_id, media_id)
        return _media(m, ctx.tenant_id)
    m.status, m.bytes, m.duration_s, m.width, m.height, m.has_audio = "ready", path.stat().st_size, round(p.duration, 2), p.width, p.height, p.has_audio
    return _media(m, ctx.tenant_id)


async def _row(db: AsyncSession, media_id: uuid.UUID) -> YtMedia:
    m = await db.get(YtMedia, media_id)  # RLS: this company's only
    if m is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Video not found")
    return m


@router.get("/media/{media_id}")
async def media_detail(media_id: uuid.UUID, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    return _media(await _row(db, media_id), ctx.tenant_id, with_transcript=True)


@router.get("/media/{media_id}/video")
async def media_video(media_id: uuid.UUID, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> FileResponse:
    m = await _row(db, media_id)
    try:
        path = files.video_path(get_settings().media_root, ctx.tenant_id, m.media_id)
    except files.LabError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from None
    name = m.title.replace('"', "")[:80] or "video"
    return FileResponse(path, media_type="video/mp4", filename=f"{name}{path.suffix}", content_disposition_type="inline")


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def media_delete(media_id: uuid.UUID, ctx: TenantContext = Depends(can_work), db: AsyncSession = Depends(get_db)) -> None:
    m = await _row(db, media_id)
    await db.delete(m)
    files.remove(get_settings().media_root, ctx.tenant_id, media_id)


OPTIONS = {"cut": jobs.CutOptions, "subtitles": jobs.SubtitleOptions, "captions": jobs.CaptionOptions, "shorts": jobs.ShortsOptions,
           "export": jobs.ExportOptions, "upload": jobs.UploadOptions}


class TranscribeOptions(BaseModel):
    language: str | None = Field(default=None, pattern="^(az|ru|en|tr)$")


@router.post("/media/{media_id}/{kind}", status_code=status.HTTP_202_ACCEPTED)
async def media_job(media_id: uuid.UUID, kind: str, body: dict[str, Any], ctx: TenantContext = Depends(can_work),
                    db: AsyncSession = Depends(get_db), lab: jobs.Lab = Depends(get_lab)) -> dict[str, Any]:
    await credits.require_addon(db)
    m = await _row(db, media_id)
    if m.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "The video is not ready yet")
    model = TranscribeOptions if kind == "transcribe" else OPTIONS.get(kind)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown work")
    try:
        opts = model.model_validate(body)
    except ValidationError as e:
        raise HTTPException(422, e.errors()[0]["msg"]) from None
    if kind in ("subtitles", "captions", "shorts") and not (m.transcript or {}).get("segments"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Transcribe the video first")
    if kind in ("captions", "upload") and (lab.yt is None or lab.vault is None):
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect the YouTube channel first")
    if kind == "export":
        try:
            jobs.export_ranges(m.duration_s or 0, opts)
        except jobs.JobError as e:
            raise HTTPException(422, str(e)) from None
    jid = await jobs.start(lab.engine, ctx.tenant_id, m, kind, opts, ctx.account.account_id)
    by = ctx.account.account_id
    run = {
        "transcribe": lambda: lead.spawn(jobs.run_transcribe, lab=lab, job_id=jid, media_id=media_id, language=opts.language),
        "cut": lambda: lead.spawn(jobs.run_cut, lab=lab, job_id=jid, media_id=media_id, opts=opts, by=by),
        "subtitles": lambda: lead.spawn(jobs.run_subtitles, lab=lab, job_id=jid, media_id=media_id, opts=opts, by=by),
        "captions": lambda: lead.spawn(jobs.run_captions, lab=lab, job_id=jid, media_id=media_id, opts=opts),
        "shorts": lambda: lead.spawn(jobs.run_shorts, lab=lab, job_id=jid, media_id=media_id, opts=opts, by=by),
        "export": lambda: lead.spawn(jobs.run_export, lab=lab, job_id=jid, media_id=media_id, opts=opts, by=by),
        "upload": lambda: lead.spawn(jobs.run_upload, lab=lab, job_id=jid, media_id=media_id, opts=opts),
    }
    run[kind]()
    return {"job_id": jid}


@router.post("/generate", status_code=status.HTTP_202_ACCEPTED)
async def generate(options: str = Form(...), image: UploadFile | None = File(default=None), ctx: TenantContext = Depends(can_work),
                   db: AsyncSession = Depends(get_db), lab: jobs.Lab = Depends(get_lab)) -> dict[str, Any]:
    await credits.require_addon(db)
    try:
        opts = jobs.GenerateOptions.model_validate(json.loads(options))
        models.get(opts.model)
    except (ValidationError, ValueError, KeyError):
        raise HTTPException(422, "Check the video options") from None
    if lab.video_fal is None or lab.llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI video is not configured on this server")
    data = None
    if image is not None:
        raw = await image.read(images.MAX_UPLOAD_BYTES + 1)
        try:
            from del_social.youtube.thumbs import as_jpeg

            data = as_jpeg(raw, 1920)
        except images.ImageRejected as e:
            raise HTTPException(422, str(e)) from None
    jid = await jobs.start(lab.engine, ctx.tenant_id, None, "generate", opts, ctx.account.account_id)
    lead.spawn(jobs.run_generate, lab=lab, job_id=jid, opts=opts, image=data, by=ctx.account.account_id)
    return {"job_id": jid, "credits": jobs.cost("generate", None, opts)}


@router.get("/jobs/{job_id}")
async def job_detail(job_id: uuid.UUID, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    j = await db.get(YtJob, job_id)
    if j is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return _job(j)


@public_router.get("/lab-files/{tenant_id}/{media_id}/{name}", include_in_schema=False)
async def lab_file(tenant_id: uuid.UUID, media_id: uuid.UUID, name: str, exp: int = Query(...), sig: str = Query(..., max_length=64),
                   db: AsyncSession = Depends(get_db)) -> FileResponse:
    """For fal.ai only: a signed, expiring link to one file (audio for transcription, a start image)."""
    s = get_settings()
    try:
        ok = files.check_link(s.secret_key, tenant_id, media_id, name, exp, sig)
    except MediaNotConfigured:
        ok = False
    path = files.folder(s.media_root, tenant_id, media_id) / name
    if not ok or not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await set_tenant(db, tenant_id)
    return FileResponse(path)
