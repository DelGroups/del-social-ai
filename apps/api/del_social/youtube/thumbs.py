"""Thumbnail studio: designs as data, layers as files, the image rendered by code (render.py).

Files per thumbnail: <media_root>/<tenant>/yt-thumbs/<thumbnail_id>/background.jpg, cutout.png,
render.jpg. Backgrounds come from the video's current thumbnail on YouTube, an upload, an AI image
(text-free, CLAUDE.md principle 8) or an AI edit of the current background; a cut-out removes the
background of the subject so it can stand on a new one. AI work costs credits and is refunded if it
fails. Applying sends the rendered JPEG to YouTube (thumbnails.set).
"""
import base64
import io
import logging
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from PIL import Image, ImageOps
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents import youtube as agents
from del_social.billing import credits
from del_social.connections.youtube import YouTubeClient, YouTubeError
from del_social.core.config import Settings
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.llm import LLM, LLMError
from del_social.media import images
from del_social.media.fal import FalClient, FalError
from del_social.models import YtThumbnail, YtVideo
from del_social.youtube import render, reports
from del_social.youtube.channel import Studio, creds, load, report_language

log = logging.getLogger(__name__)

TEXT_FREE = ("No text, letters, numbers, words, captions, logos or watermarks anywhere in the image. "
             "Leave a clean area for a headline. High contrast, vivid, sharp, 16:9 YouTube thumbnail background.")
SIDE = {"left_text": "left", "right_text": "right", "top_banner": "top", "bottom_bar": "bottom", "corner_badge": "left",
        "minimal": "bottom", "center_big": "centre", "split": "top"}


class ThumbError(ValueError):
    """Safe to show."""


def folder(root: str, tenant_id: uuid.UUID, thumbnail_id: uuid.UUID) -> Path:
    return Path(root) / str(tenant_id) / "yt-thumbs" / str(thumbnail_id)


def _read(path: Path) -> Image.Image | None:
    if not path.exists():
        return None
    with Image.open(path) as img:
        img.load()
        return img.copy()


def _save(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


def rerender(root: str, row: YtThumbnail) -> bytes:
    d = folder(root, row.tenant_id, row.thumbnail_id)
    data = render.render(render.Spec.model_validate(row.spec), _read(d / "background.jpg"), _read(d / "cutout.png"))
    _save(d / "render.jpg", data)
    return data


def as_jpeg(data: bytes, max_side: int = 1920) -> bytes:
    """An upload or model output → a clean RGB JPEG (checked like every photo upload)."""
    images.inspect(data, min_side=200)
    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img).convert("RGB")
        img.thumbnail((max_side, max_side))
        out = io.BytesIO()
        img.save(out, "JPEG", quality=92)
        return out.getvalue()


def data_uri(data: bytes, mime: str = "image/jpeg") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


async def youtube_frame(http: httpx.AsyncClient, video_id: str) -> bytes | None:
    """The video's current thumbnail at the best size YouTube serves."""
    for name in ("maxresdefault", "sddefault", "hqdefault"):
        try:
            r = await http.get(f"https://i.ytimg.com/vi/{video_id}/{name}.jpg", timeout=20.0)
        except httpx.HTTPError:
            continue
        if r.status_code == 200 and len(r.content) > 2000:
            return r.content
    return None


# --- rows ---


async def create(engine: AsyncEngine, root: str, studio: Studio, video_id: str | None, spec: render.Spec,
                 background: bytes | None, source: dict[str, Any], by: uuid.UUID | None) -> uuid.UUID:
    tid = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, studio.tenant_id)
        row = YtThumbnail(thumbnail_id=tid, tenant_id=studio.tenant_id, connection_id=studio.connection_id, video_id=video_id,
                          spec=spec.model_dump(), background=source, created_by=by, status="ready")
        db.add(row)
        await db.flush()
        if background:
            _save(folder(root, studio.tenant_id, tid) / "background.jpg", as_jpeg(background))
        rerender(root, row)
    return tid


async def update(engine: AsyncEngine, tenant_id: uuid.UUID, tid: uuid.UUID, **values: Any) -> YtThumbnail:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        row = await db.get(YtThumbnail, tid)
        for k, v in values.items():
            setattr(row, k, v)
        return row


def delete_files(root: str, tenant_id: uuid.UUID, tid: uuid.UUID) -> None:
    shutil.rmtree(folder(root, tenant_id, tid), ignore_errors=True)


# --- AI work (credits first, refund on failure) ---


async def _spend(engine: AsyncEngine, tenant_id: uuid.UUID, work: str, ref: uuid.UUID, by: uuid.UUID | None) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        await credits.spend(db, tenant_id, credits.COST[work], work, ref, by)


async def _refund(engine: AsyncEngine, tenant_id: uuid.UUID, ref: uuid.UUID) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        await credits.refund(db, tenant_id, ref)


def _first_url(out: dict[str, Any]) -> str:
    files = out.get("images") or ([out["image"]] if out.get("image") else [])
    if not files or not files[0].get("url"):
        raise FalError("The image model returned no image")
    return files[0]["url"]


async def ai_background(fal: FalClient, settings: Settings, prompt: str, layout: str) -> bytes:
    full = f"{prompt.strip()}. Put the main subject away from the {SIDE.get(layout, 'left')} side, where the headline goes. {TEXT_FREE}"
    out = await fal.run(settings.thumbnail_image_model, {"prompt": full, "image_size": "landscape_16_9", "output_format": "jpeg",
                                                         "num_images": 1})
    return await fal.download(_first_url(out), images.MAX_UPLOAD_BYTES)


async def ai_edit(fal: FalClient, settings: Settings, current: bytes, request: str) -> bytes:
    prompt = f"{request.strip()}. Keep it a photographic 16:9 YouTube thumbnail background. {TEXT_FREE}"
    out = await fal.run(settings.image_edit_model, {"prompt": prompt, "image_urls": [data_uri(current)], "output_format": "jpeg"})
    return await fal.download(_first_url(out), images.MAX_UPLOAD_BYTES)


async def cutout(fal: FalClient, settings: Settings, source: bytes) -> bytes:
    out = await fal.run(settings.cutout_model, {"image_url": data_uri(source), "output_format": "png"})
    png = await fal.download(_first_url(out), images.MAX_UPLOAD_BYTES)
    with Image.open(io.BytesIO(png)) as img:
        if img.mode != "RGBA":
            raise FalError("The background remover returned no transparent image")
    return png


async def run_background(*, engine: AsyncEngine, settings: Settings, fal: FalClient, tenant_id: uuid.UUID, thumbnail_id: uuid.UUID,
                         mode: Literal["ai", "edit"], prompt: str, ref: uuid.UUID) -> None:
    """Background job: a new AI background (credits already spent under `ref`)."""
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        row = await db.get(YtThumbnail, thumbnail_id)
    d = folder(settings.media_root, tenant_id, thumbnail_id)
    try:
        if mode == "ai":
            data = await ai_background(fal, settings, prompt, row.spec.get("layout", "left_text"))
        else:
            current = (d / "background.jpg").read_bytes() if (d / "background.jpg").exists() else None
            if current is None:
                raise ThumbError("There is no background to edit yet")
            data = await ai_edit(fal, settings, current, prompt)
        _save(d / "background.jpg", as_jpeg(data))
        row = await update(engine, tenant_id, thumbnail_id, status="ready", error=None, rev=row.rev + 1,
                           background={"source": mode, "prompt": prompt[:500], "model": settings.thumbnail_image_model if mode == "ai" else settings.image_edit_model})
        rerender(settings.media_root, row)
    except (FalError, ThumbError, images.ImageRejected, OSError) as e:
        log.warning("thumbnail background failed: %s", e)
        await _refund(engine, tenant_id, ref)
        await update(engine, tenant_id, thumbnail_id, status="ready", error=f"{e} (credits refunded)"[:300])


async def run_cutout(*, engine: AsyncEngine, settings: Settings, fal: FalClient, tenant_id: uuid.UUID, thumbnail_id: uuid.UUID,
                     source: bytes, ref: uuid.UUID) -> None:
    d = folder(settings.media_root, tenant_id, thumbnail_id)
    try:
        png = await cutout(fal, settings, source)
        _save(d / "cutout.png", png)
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            row = await db.get(YtThumbnail, thumbnail_id)
            spec = dict(row.spec)
            if spec.get("subject", "none") == "none":
                spec["subject"] = "left" if spec.get("layout") == "right_text" else "right"
            row.spec, row.status, row.error, row.rev = spec, "ready", None, row.rev + 1
        rerender(settings.media_root, row)
    except (FalError, images.ImageRejected, OSError) as e:
        log.warning("thumbnail cutout failed: %s", e)
        await _refund(engine, tenant_id, ref)
        await update(engine, tenant_id, thumbnail_id, status="ready", error=f"{e} (credits refunded)"[:300])


async def run_design(*, engine: AsyncEngine, settings: Settings, llm: LLM, fal: FalClient | None, http: httpx.AsyncClient,
                     tenant_id: uuid.UUID, video_id: str, wishes: str, ai_backgrounds: bool, ids: list[uuid.UUID],
                     by: uuid.UUID | None) -> None:
    """Background job: three concepts from the designer, each rendered on the video's frame or an AI background.

    The rows in `ids` exist already (status working) so the panel shows three cards filling in.
    """
    studio = await load(engine, tenant_id)
    frame = await youtube_frame(http, video_id)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            video = await db.get(YtVideo, (studio.connection_id, video_id))
            lang = await report_language(db, studio.settings)
        text = (
            f"<report_language>{lang}</report_language>\n"
            f"<video>\n{reports.dumps({'title': video.title if video else '', 'description': (video.description if video else '')[:1500], 'channel': studio.channel_block()})}\n</video>\n"
            f"<wishes>{wishes or 'none'}</wishes>\n<styles>layouts: {', '.join(render.LAYOUTS)}; palettes: {', '.join(render.PALETTES)}</styles>"
        )
        concepts = (await agents.thumbnail_concepts(llm, tenant_id, text, [frame] if frame else None)).output.concepts
    except (LLMError, YouTubeError) as e:
        for tid in ids:
            if ai_backgrounds:
                await _refund(engine, tenant_id, tid)
            await update(engine, tenant_id, tid, status="failed", error=str(e)[:300])
        return
    language = (studio.settings.languages or ["az"])[0]
    for tid, concept in zip(ids, concepts + concepts[:1] * (len(ids) - len(concepts))):
        spec = render.Spec(text=concept.text, emphasis=concept.emphasis, layout=concept.layout, palette=concept.palette,
                           language=language)
        d = folder(settings.media_root, tenant_id, tid)
        source: dict[str, Any] = {"source": "youtube" if frame else "palette", "concept": concept.model_dump()}
        error = None
        try:
            if ai_backgrounds and fal is not None:
                _save(d / "background.jpg", as_jpeg(await ai_background(fal, settings, concept.background_prompt, concept.layout)))
                source = {"source": "ai", "prompt": concept.background_prompt, "concept": concept.model_dump()}
            elif frame:
                _save(d / "background.jpg", as_jpeg(frame))
        except (FalError, images.ImageRejected) as e:
            await _refund(engine, tenant_id, tid)
            error = f"AI background failed, the video frame is used instead ({e}); credits refunded"[:300]
            if frame:
                _save(d / "background.jpg", as_jpeg(frame))
        row = await update(engine, tenant_id, tid, spec=spec.model_dump(), background=source, status="ready", error=error)
        rerender(settings.media_root, row)


async def apply(engine: AsyncEngine, yt: YouTubeClient, vault: TokenVault, root: str, tenant_id: uuid.UUID,
                thumbnail_id: uuid.UUID, video_id: str) -> None:
    studio = await load(engine, tenant_id)
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        row = await db.get(YtThumbnail, thumbnail_id)
    path = folder(root, tenant_id, thumbnail_id) / "render.jpg"
    data = path.read_bytes() if path.exists() else rerender(root, row)
    try:
        await yt.set_thumbnail(creds(vault, studio), video_id, data)
    except YouTubeError as e:
        if e.status == 403:
            raise YouTubeError("YouTube refused the thumbnail: custom thumbnails need a phone-verified channel "
                               "(youtube.com/verify) and permission to upload them.", 403, e.reason) from None
        raise
    await update(engine, tenant_id, thumbnail_id, status="applied", video_id=video_id, applied_at=datetime.now(UTC))
