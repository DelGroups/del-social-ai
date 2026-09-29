"""Video lab jobs: each is paid before it starts, runs in the background, reports progress, and is
refunded when it fails. Times, ranges and credits are code; models only read, choose and write.

transcribe  speech → timed segments (fal.ai Whisper)          credits per started 10 minutes
cut         remove silences (+ loudness), subtitles follow     credits per started minute of the source
subtitles   burn styled subtitles in, optionally translated    credits per started minute (+1 to translate)
captions    upload subtitles (optionally translated) to a YouTube video as a caption track
shorts      the model picks moments, code cuts vertical Shorts with subtitles and a headline
export      trim / speed / reframe / loudness                  credits per started minute of the result
generate    AI video clips from an idea, in a chosen model and style, joined into one video
upload      send a lab video to YouTube (title, description, visibility, schedule, AI disclosure)
"""
import logging
import math
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents import youtube as agents
from del_social.billing import credits
from del_social.connections.youtube import YouTubeClient, YouTubeError
from del_social.core.config import Settings
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.llm import LLM, LLMError
from del_social.media.fal import FalClient, FalError
from del_social.models import YtJob, YtMedia
from del_social.youtube import render as thumb_render
from del_social.youtube.channel import creds, load
from del_social.youtube.lab import ffmpeg, files, models, subs

log = logging.getLogger(__name__)
FONTS = thumb_render.FONT_DIR


class Lab:
    """What a job needs. A plain class: FastAPI copies dataclasses given as dependencies (and clients can't be copied)."""

    def __init__(self, *, engine: AsyncEngine, settings: Settings, tenant_id: uuid.UUID, llm: LLM | None = None,
                 fal: FalClient | None = None, video_fal: FalClient | None = None, yt: YouTubeClient | None = None,
                 vault: TokenVault | None = None, http: httpx.AsyncClient | None = None):
        self.engine, self.settings, self.tenant_id = engine, settings, tenant_id
        self.llm, self.fal, self.video_fal, self.yt, self.vault, self.http = llm, fal, video_fal, yt, vault, http


class JobError(ValueError):
    """Safe to show."""


# --- options (validated by the routes) ---


class CutOptions(BaseModel):
    level: Literal["gentle", "normal", "tight"] = "normal"
    loudness: bool = True


class SubtitleOptions(BaseModel):
    style: subs.SubStyle = Field(default_factory=subs.SubStyle)
    translate_to: Literal["az", "ru", "en", "tr"] | None = None
    loudness: bool = False


class CaptionOptions(BaseModel):
    video_id: str = Field(min_length=1, max_length=32)
    translate_to: Literal["az", "ru", "en", "tr"] | None = None
    language: Literal["az", "ru", "en", "tr"] = "az"  # the language of the track uploaded


class ShortsOptions(BaseModel):
    count: int = Field(default=3, ge=1, le=5)
    frame: Literal["vertical_center", "vertical_blur"] = "vertical_blur"
    crop_x: float = Field(default=0.5, ge=0, le=1)
    style: subs.SubStyle = Field(default_factory=lambda: subs.SubStyle(position="middle", size="l", uppercase=True))
    hook: bool = True


class ExportOptions(BaseModel):
    start: float = Field(default=0, ge=0)
    end: float | None = Field(default=None, gt=0)
    cuts: list[tuple[float, float]] = Field(default_factory=list, max_length=50)  # parts to remove
    speed: float = Field(default=1.0, ge=0.5, le=2.0)
    frame: ffmpeg.Frame = "original"
    crop_x: float = Field(default=0.5, ge=0, le=1)
    loudness: bool = True
    subtitles: bool = False
    style: subs.SubStyle = Field(default_factory=subs.SubStyle)


class GenerateOptions(BaseModel):
    idea: str = Field(min_length=3, max_length=1500)
    model: str = Field(default="standard", max_length=40)
    style: Literal["cinematic", "realistic", "documentary", "anime", "3d", "product", "retro", "drone"] = "cinematic"
    camera: str = Field(default="", max_length=200)
    mood: str = Field(default="", max_length=200)
    seconds: int = Field(default=5, ge=3, le=15)
    aspect: Literal["16:9", "9:16", "1:1"] = "16:9"
    scenes: int = Field(default=1, ge=1, le=6)
    captions: bool = False
    language: Literal["az", "ru", "en", "tr"] = "az"


class UploadOptions(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=60)
    privacy: Literal["private", "unlisted", "public"] = "private"
    publish_at: datetime | None = None
    made_for_kids: bool = False
    language: str = Field(default="az", max_length=5)


def minutes(seconds: float) -> int:
    return max(1, math.ceil(seconds / 60))


def cost(kind: str, media: YtMedia | None, opts: BaseModel) -> int:
    """Credits for a job, from the source's length and the options (all known before it starts)."""
    per_min, dur = credits.COST["render_min"], (media.duration_s or 0) if media else 0
    if kind == "transcribe":
        return max(1, math.ceil(dur / 600)) * credits.COST["transcribe_10min"]
    if kind == "cut":
        return minutes(dur) * per_min
    if kind == "subtitles":
        return minutes(dur) * per_min + (credits.COST["metadata"] if opts.translate_to else 0)
    if kind == "captions":
        return credits.COST["metadata"] if opts.translate_to else 0
    if kind == "shorts":
        return credits.COST["shorts_pick"] + opts.count * per_min
    if kind == "export":
        return minutes(export_length(dur, opts) if dur else 60) * per_min
    if kind == "generate":
        return models.credits_for(models.get(opts.model), clip_seconds(models.get(opts.model), opts.seconds), opts.scenes)
    return 0


def clip_seconds(model: models.VideoModel, wanted: int) -> int:
    """The model's allowed length closest to what was asked."""
    return min(model.durations, key=lambda d: abs(d - wanted))


def export_ranges(duration: float, o: ExportOptions) -> list[tuple[float, float]]:
    end = min(o.end or duration, duration)
    if end <= o.start:
        raise JobError("The end must be after the start")
    ranges = [(o.start, end)]
    for cs, ce in sorted(o.cuts):
        nxt = []
        for s, e in ranges:
            if ce <= s or cs >= e:
                nxt.append((s, e))
                continue
            if cs > s:
                nxt.append((s, cs))
            if ce < e:
                nxt.append((ce, e))
        ranges = nxt
    return [(round(s, 3), round(e, 3)) for s, e in ranges if e - s > 0.05]


def export_length(duration: float, o: ExportOptions) -> float:
    return ffmpeg.total(export_ranges(duration, o)) / o.speed


# --- rows ---


async def start(engine: AsyncEngine, tenant_id: uuid.UUID, media: YtMedia | None, kind: str, opts: BaseModel, by: uuid.UUID | None) -> uuid.UUID:
    """The job row, committed, with its credits spent (raises CreditError before anything runs)."""
    jid = uuid.uuid4()
    amount = cost(kind, media, opts)
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        if amount:
            await credits.spend(db, tenant_id, amount, f"lab_{kind}", jid, by)
        db.add(YtJob(job_id=jid, tenant_id=tenant_id, media_id=media.media_id if media else None, kind=kind,
                     options=opts.model_dump(mode="json"), credits=amount, created_by=by))
    return jid


async def _set(engine: AsyncEngine, tenant_id: uuid.UUID, jid: uuid.UUID, **values: Any) -> YtJob:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        job = await db.get(YtJob, jid)
        for k, v in values.items():
            setattr(job, k, v)
        if values.get("status") in ("done", "failed"):
            job.finished_at = datetime.now(UTC)
            if values["status"] == "failed" and job.credits:
                await credits.refund(db, tenant_id, jid)
        return job


async def _media(engine: AsyncEngine, tenant_id: uuid.UUID, media_id: uuid.UUID) -> YtMedia:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        m = await db.get(YtMedia, media_id)
        if m is None:
            raise JobError("The video is gone (lab files are kept for 14 days)")
        return m


async def new_media(engine: AsyncEngine, tenant_id: uuid.UUID, kind: str, title: str, source: uuid.UUID | None,
                    by: uuid.UUID | None, filename: str = "video.mp4", expected: int | None = None) -> uuid.UUID:
    mid = uuid.uuid4()
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        db.add(YtMedia(media_id=mid, tenant_id=tenant_id, kind=kind, title=title[:200], filename=filename,
                       source_media_id=source, created_by=by, expected_bytes=expected))
    return mid


async def ready_media(lab: Lab, media_id: uuid.UUID, transcript: dict[str, Any] | None = None) -> YtMedia:
    """Probe the finished file and mark the media ready."""
    path = files.video_path(lab.settings.media_root, lab.tenant_id, media_id)
    p = await ffmpeg.probe(path)
    async with AsyncSession(lab.engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, lab.tenant_id)
        m = await db.get(YtMedia, media_id)
        m.status, m.bytes, m.duration_s, m.width, m.height, m.has_audio = "ready", path.stat().st_size, round(p.duration, 2), p.width, p.height, p.has_audio
        if transcript is not None:
            m.transcript = transcript
        return m


async def _run(lab: Lab, jid: uuid.UUID, work) -> None:
    """Run one job body with progress; any failure refunds its credits."""
    await _set(lab.engine, lab.tenant_id, jid, status="running", progress=1)

    async def progress(pct: int) -> None:
        await _set(lab.engine, lab.tenant_id, jid, progress=pct)

    try:
        result = await work(progress)
        await _set(lab.engine, lab.tenant_id, jid, status="done", progress=100, result=result)
    except (ffmpeg.FFmpegError, JobError, files.LabError, FalError, LLMError, YouTubeError) as e:
        log.warning("lab job %s failed: %s", jid, e)
        await _set(lab.engine, lab.tenant_id, jid, status="failed", error=f"{e}"[:400])
    except Exception:  # noqa: BLE001 — never leave a paid job hanging
        log.exception("lab job %s crashed", jid)
        await _set(lab.engine, lab.tenant_id, jid, status="failed", error="Something went wrong; the credits were refunded.")


def _segments(m: YtMedia) -> list[dict[str, Any]]:
    segs = (m.transcript or {}).get("segments") or []
    if not segs:
        raise JobError("Transcribe the video first")
    return segs


# --- transcribe ---


async def run_transcribe(*, lab: Lab, job_id: uuid.UUID, media_id: uuid.UUID, language: str | None) -> None:
    async def work(progress):
        if lab.fal is None:
            raise JobError("Speech recognition is not configured on this server")
        root = lab.settings.media_root
        d = files.folder(root, lab.tenant_id, media_id)
        await ffmpeg.audio_for_transcription(files.video_path(root, lab.tenant_id, media_id), d / "audio.mp3")
        await progress(20)
        link = files.public_link(lab.settings.media_public_url, lab.settings.secret_key, lab.tenant_id, media_id, "audio.mp3")
        payload = {"audio_url": link, "task": "transcribe", "chunk_level": "segment", "version": "3"}
        if language:
            payload["language"] = language
        out = await lab.fal.run(lab.settings.transcribe_model, payload)
        segs = subs.from_chunks(out.get("chunks") or [])
        if not segs:
            raise JobError("No speech was found in this video")
        (d / "audio.mp3").unlink(missing_ok=True)
        async with AsyncSession(lab.engine) as db, db.begin():
            await set_tenant(db, lab.tenant_id)
            m = await db.get(YtMedia, media_id)
            m.transcript = {"language": language or out.get("inferred_languages", [None])[0], "segments": segs,
                            "text": (out.get("text") or "")[:20000]}
        return {"segments": len(segs)}

    await _run(lab, job_id, work)


# --- cut silences ---


async def run_cut(*, lab: Lab, job_id: uuid.UUID, media_id: uuid.UUID, opts: CutOptions, by: uuid.UUID | None) -> None:
    async def work(progress):
        src = await _media(lab.engine, lab.tenant_id, media_id)
        path = files.video_path(lab.settings.media_root, lab.tenant_id, media_id)
        quiet = await ffmpeg.silences(path, opts.level)
        keep = ffmpeg.keep_ranges(src.duration_s or 0, quiet, ffmpeg.SILENCE[opts.level][2])
        if not keep:
            raise JobError("The whole video is silent")
        out = await new_media(lab.engine, lab.tenant_id, "render", f"{src.title} · cut", media_id, by)
        dst = files.folder(lab.settings.media_root, lab.tenant_id, out) / "video.mp4"
        dst.parent.mkdir(parents=True, exist_ok=True)
        await ffmpeg.render(path, dst, ffmpeg.total(keep), src.has_audio, progress, ranges=keep, loudness=opts.loudness)
        transcript = {"segments": subs.retime(src.transcript["segments"], keep)} if src.transcript else None
        await ready_media(lab, out, transcript)
        return {"media_id": str(out), "removed_seconds": round((src.duration_s or 0) - ffmpeg.total(keep), 1), "parts": len(keep)}

    await _run(lab, job_id, work)


# --- subtitles ---


async def translated(lab: Lab, segs: list[dict[str, Any]], language: str) -> list[dict[str, Any]]:
    if lab.llm is None:
        raise JobError("Translation is not configured on this server")
    listing = [{"index": i, "text": s["text"]} for i, s in enumerate(segs)]
    out = (await agents.translate_segments(lab.llm, lab.tenant_id, f"<language>{language}</language>\n<segments>\n"
                                           + "\n".join(f"{x['index']}: {x['text']}" for x in listing) + "\n</segments>")).output
    by_index = {s.index: s.text for s in out.segments}
    return [s | {"text": by_index.get(i, s["text"])} for i, s in enumerate(segs)]  # a missing line keeps the original


async def run_subtitles(*, lab: Lab, job_id: uuid.UUID, media_id: uuid.UUID, opts: SubtitleOptions, by: uuid.UUID | None) -> None:
    async def work(progress):
        src = await _media(lab.engine, lab.tenant_id, media_id)
        segs = _segments(src)
        if opts.translate_to:
            segs = await translated(lab, segs, opts.translate_to)
        out = await new_media(lab.engine, lab.tenant_id, "render", f"{src.title} · subtitles", media_id, by)
        d = files.folder(lab.settings.media_root, lab.tenant_id, out)
        d.mkdir(parents=True, exist_ok=True)
        style = opts.style.model_copy(update={"language": opts.translate_to or opts.style.language})
        (d / "subs.ass").write_text(subs.ass(segs, style, src.width or 1920, src.height or 1080), encoding="utf-8")
        (d / "subs.srt").write_text(subs.srt(segs), encoding="utf-8")
        await ffmpeg.render(files.video_path(lab.settings.media_root, lab.tenant_id, media_id), d / "video.mp4", src.duration_s or 0,
                            src.has_audio, progress, subtitles=d / "subs.ass", fonts=FONTS, loudness=opts.loudness)
        await ready_media(lab, out, {"segments": segs})
        return {"media_id": str(out)}

    await _run(lab, job_id, work)


async def run_captions(*, lab: Lab, job_id: uuid.UUID, media_id: uuid.UUID, opts: CaptionOptions) -> None:
    async def work(progress):
        if lab.yt is None or lab.vault is None:
            raise JobError("YouTube is not connected")
        src = await _media(lab.engine, lab.tenant_id, media_id)
        segs = _segments(src)
        lang = opts.language
        if opts.translate_to:
            segs, lang = await translated(lab, segs, opts.translate_to), opts.translate_to
        studio = await load(lab.engine, lab.tenant_id)
        names = {"az": "Azərbaycanca", "ru": "Русский", "en": "English", "tr": "Türkçe"}
        await lab.yt.insert_caption(creds(lab.vault, studio), opts.video_id, lang, names[lang], subs.srt(segs))
        return {"video_id": opts.video_id, "language": lang}

    await _run(lab, job_id, work)


# --- shorts ---


def pick_ranges(picks: list[agents.ShortPick], segs: list[dict[str, Any]]) -> list[tuple[agents.ShortPick, float, float]]:
    """Validate the model's segment choices into cut times: 10–65 s, no overlaps, inside the video."""
    out: list[tuple[agents.ShortPick, float, float]] = []
    for p in picks:
        if not (0 <= p.first <= p.last < len(segs)):
            continue
        start, end = segs[p.first]["start"], segs[p.last]["end"]
        if end - start > 65:  # too long: drop segments from the end until it fits
            last = p.last
            while last > p.first and segs[last]["end"] - start > 60:
                last -= 1
            end = segs[last]["end"]
        if end - start < 10 or any(not (end <= s or start >= e) for _, s, e in out):
            continue
        out.append((p, round(max(0.0, start - 0.15), 2), round(end + 0.35, 2)))
    return out


async def run_shorts(*, lab: Lab, job_id: uuid.UUID, media_id: uuid.UUID, opts: ShortsOptions, by: uuid.UUID | None) -> None:
    async def work(progress):
        if lab.llm is None:
            raise JobError("The AI team is not configured on this server")
        src = await _media(lab.engine, lab.tenant_id, media_id)
        segs = _segments(src)
        listing = "\n".join(f"{i} ({s['end'] - s['start']:.1f}s): {s['text']}" for i, s in enumerate(segs))
        picks = (await agents.shorts(lab.llm, lab.tenant_id, f"<video>{src.title}</video>\n<count>{opts.count}</count>\n"
                                                             f"<segments>\n{listing}\n</segments>")).output.shorts
        chosen = pick_ranges(picks, segs)[: opts.count]
        if not chosen:
            raise JobError("No moment of 10–60 seconds that stands on its own was found")
        await progress(10)
        path = files.video_path(lab.settings.media_root, lab.tenant_id, media_id)
        made = []
        for n, (p, start, end) in enumerate(chosen):
            out = await new_media(lab.engine, lab.tenant_id, "render", p.title, media_id, by)
            d = files.folder(lab.settings.media_root, lab.tenant_id, out)
            d.mkdir(parents=True, exist_ok=True)
            local = subs.retime(segs, [(start, end)])
            (d / "subs.ass").write_text(subs.ass(local, opts.style, 1080, 1920, p.hook if opts.hook else None), encoding="utf-8")

            async def part(pct: int, n: int = n) -> None:
                await progress(10 + int((n + pct / 100) / len(chosen) * 89))

            await ffmpeg.render(path, d / "video.mp4", end - start, src.has_audio, part, ranges=[(start, end)], frame=opts.frame,
                                crop_x=opts.crop_x, subtitles=d / "subs.ass", fonts=FONTS, loudness=True)
            await ready_media(lab, out, {"segments": local})
            made.append({"media_id": str(out), "title": p.title, "hook": p.hook, "why": p.why, "seconds": round(end - start, 1)})
        return {"shorts": made}

    await _run(lab, job_id, work)


# --- export ---


async def run_export(*, lab: Lab, job_id: uuid.UUID, media_id: uuid.UUID, opts: ExportOptions, by: uuid.UUID | None) -> None:
    async def work(progress):
        src = await _media(lab.engine, lab.tenant_id, media_id)
        ranges = export_ranges(src.duration_s or 0, opts)
        out = await new_media(lab.engine, lab.tenant_id, "render", f"{src.title} · edit", media_id, by)
        d = files.folder(lab.settings.media_root, lab.tenant_id, out)
        d.mkdir(parents=True, exist_ok=True)
        segs = subs.retime(src.transcript["segments"], ranges, opts.speed) if src.transcript else None
        sub_path = None
        if opts.subtitles:
            if not segs:
                raise JobError("Transcribe the video first to add subtitles")
            w, h = ffmpeg.SIZES.get(opts.frame, (src.width or 1920, src.height or 1080))
            sub_path = d / "subs.ass"
            sub_path.write_text(subs.ass(segs, opts.style, w, h), encoding="utf-8")
        whole = len(ranges) == 1 and ranges[0] == (0, round(src.duration_s or 0, 3))
        await ffmpeg.render(files.video_path(lab.settings.media_root, lab.tenant_id, media_id), d / "video.mp4",
                            ffmpeg.total(ranges) / opts.speed, src.has_audio, progress, ranges=None if whole else ranges,
                            speed=opts.speed, frame=opts.frame, crop_x=opts.crop_x, loudness=opts.loudness, subtitles=sub_path,
                            fonts=FONTS if sub_path else None)
        await ready_media(lab, out, {"segments": segs} if segs else None)
        return {"media_id": str(out)}

    await _run(lab, job_id, work)


# --- AI video ---

STYLE = {
    "cinematic": "cinematic film look, shallow depth of field, dramatic lighting, anamorphic lens",
    "realistic": "photorealistic, natural light, true-to-life colours",
    "documentary": "documentary footage, handheld camera, natural light",
    "anime": "anime style, vibrant colours, clean line art",
    "3d": "3D animation, soft global illumination, Pixar-like rendering",
    "product": "premium product commercial, studio lighting, slow smooth camera move, clean background",
    "retro": "vintage 16mm film, grain, warm faded colours",
    "drone": "aerial drone footage, smooth sweeping movement, wide landscape",
}


async def run_generate(*, lab: Lab, job_id: uuid.UUID, opts: GenerateOptions, image: bytes | None, by: uuid.UUID | None) -> None:
    async def work(progress):
        if lab.video_fal is None or lab.llm is None:
            raise JobError("AI video is not configured on this server")
        model = models.get(opts.model)
        seconds = clip_seconds(model, opts.seconds)
        aspect = opts.aspect if opts.aspect in model.aspects else model.aspects[0]
        plan = (await agents.video_plan(lab.llm, lab.tenant_id, (
            f"<idea>{opts.idea}</idea>\n<style>{opts.style}: {STYLE[opts.style]}; camera: {opts.camera or 'your choice'}; "
            f"mood: {opts.mood or 'your choice'}</style>\n<scenes>{opts.scenes}</scenes>\n<seconds>{seconds}</seconds>\n<aspect>{aspect}</aspect>"
        ))).output.scenes[: opts.scenes]
        if not plan:
            raise JobError("The idea could not be turned into scenes")
        out = await new_media(lab.engine, lab.tenant_id, "generated", opts.idea[:80], None, by)
        d = files.folder(lab.settings.media_root, lab.tenant_id, out)
        d.mkdir(parents=True, exist_ok=True)
        image_url = None
        if image:
            (d / "frame.jpg").write_bytes(image)
            image_url = files.public_link(lab.settings.media_public_url, lab.settings.secret_key, lab.tenant_id, out, "frame.jpg")
        clips = []
        for i, scene in enumerate(plan):
            use_image = image_url if i == 0 and model.image_model else None
            result = await lab.video_fal.run(model.image_model if use_image else model.text_model,
                                             models.payload(model, f"{scene.prompt}. {STYLE[opts.style]}. No text, letters or logos.",
                                                            seconds, aspect, use_image))
            url = ((result.get("video") or {}).get("url")) or ((result.get("videos") or [{}])[0].get("url"))
            if not url:
                raise JobError("The video model returned no video")
            clip = d / f"clip{i}.mp4"
            clip.write_bytes(await lab.video_fal.download(url, 500 * 1024 * 1024))
            clips.append(clip)
            await progress(int((i + 1) / len(plan) * 80))
        final = d / "video.mp4"
        if len(clips) == 1 and not opts.captions:
            clips[0].rename(final)
        else:
            joined = d / "joined.mp4" if opts.captions else final
            if len(clips) > 1:
                await ffmpeg.concat(clips, joined, seconds * len(clips))
            else:
                clips[0].rename(joined)
            if opts.captions:
                p = await ffmpeg.probe(joined)
                segs = [{"start": i * seconds + 0.3, "end": (i + 1) * seconds - 0.2, "text": s.caption}
                        for i, s in enumerate(plan) if s.caption.strip()]
                (d / "subs.ass").write_text(subs.ass(segs, subs.SubStyle(language=opts.language, box=True), p.width or 1280, p.height or 720), encoding="utf-8")
                await ffmpeg.render(joined, final, p.duration, p.has_audio, None, subtitles=d / "subs.ass", fonts=FONTS)
            for c in [*clips, d / "joined.mp4"]:
                c.unlink(missing_ok=True)
        await ready_media(lab, out)
        return {"media_id": str(out), "model": model.key, "scenes": [s.model_dump() for s in plan]}

    await _run(lab, job_id, work)


# --- upload to YouTube ---


async def run_upload(*, lab: Lab, job_id: uuid.UUID, media_id: uuid.UUID, opts: UploadOptions) -> None:
    async def work(progress):
        if lab.yt is None or lab.vault is None:
            raise JobError("YouTube is not connected")
        m = await _media(lab.engine, lab.tenant_id, media_id)
        status: dict[str, Any] = {"privacyStatus": opts.privacy, "selfDeclaredMadeForKids": opts.made_for_kids,
                                  "containsSyntheticMedia": m.kind == "generated"}  # YouTube asks creators to disclose AI video
        if opts.publish_at:
            if opts.publish_at <= datetime.now(UTC):
                raise JobError("The publish time must be in the future")
            status |= {"privacyStatus": "private", "publishAt": opts.publish_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
        from del_social.youtube.kit import clean, trim_tags

        meta = {"snippet": {"title": clean(opts.title), "description": clean(opts.description), "tags": trim_tags(opts.tags),
                            "categoryId": "22", "defaultLanguage": opts.language, "defaultAudioLanguage": opts.language},
                "status": status}
        studio = await load(lab.engine, lab.tenant_id)
        vid = await lab.yt.upload_video(creds(lab.vault, studio), files.video_path(lab.settings.media_root, lab.tenant_id, media_id),
                                        meta, progress)
        async with AsyncSession(lab.engine) as db, db.begin():
            await set_tenant(db, lab.tenant_id)
            (await db.get(YtMedia, media_id)).youtube_video_id = vid
        return {"video_id": vid, "url": f"https://youtu.be/{vid}"}

    await _run(lab, job_id, work)


async def cleanup(engine: AsyncEngine, root: str) -> int:
    """Delete expired lab files and rows (called by the studio's loop)."""
    from sqlalchemy import text

    async with AsyncSession(engine) as db, db.begin():
        rows = (await db.execute(text("SELECT tenant_id, media_id FROM lab_cleanup()"))).all()
    for tenant_id, media_id in rows:
        files.remove(root, tenant_id, media_id)
        async with AsyncSession(engine) as db, db.begin():
            await set_tenant(db, tenant_id)
            m = await db.get(YtMedia, media_id)
            if m is not None:
                await db.delete(m)
    return len(rows)


async def latest_jobs(db: AsyncSession, limit: int = 40) -> list[YtJob]:
    return list((await db.scalars(select(YtJob).order_by(YtJob.created_at.desc()).limit(limit))).all())
