"""The publishing kit of one video: the model writes, code checks and assembles, the owner decides.

- Transcript: the video's own subtitles from YouTube (when it has them), grouped by code into numbered
  segments. The model picks chapter starts by segment number; code turns them into timestamps and
  checks YouTube's chapter rules (first at 0:00, at least 3, at least 10 seconds apart).
- The final description (text + chapters + links + hashtags), tag trimming to YouTube's 500-character
  limit and the SEO checks are all code.
- Applying writes title, description, tags, translations and (if asked) visibility or a publish time
  to YouTube, and can post the suggested comment for the owner to pin.
"""
import re
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents import youtube as agents
from del_social.connections.base import Credentials
from del_social.connections.youtube import YouTubeClient, YouTubeError
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.llm import LLM
from del_social.models import YtDraft, YtVideo
from del_social.youtube import reports, sync
from del_social.youtube.channel import creds, load

SEGMENT_SECONDS = 20
MAX_SEGMENTS = 160
MIN_CHAPTER_GAP = 10
TAGS_LIMIT = 500
DESCRIPTION_LIMIT = 5000
TITLE_LIMIT = 100


# --- transcript ---

_NOT_HASHTAG = re.compile(r"[^\w]")  # letters (any script), digits, underscore
_TIME = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->")


def parse_srt(srt: str) -> list[tuple[float, str]]:
    cues = []
    for block in re.split(r"\n\s*\n", srt.replace("\r", "")):
        lines = [x for x in block.strip().split("\n") if x.strip()]
        for i, line in enumerate(lines):
            if m := _TIME.search(line):
                h, mi, s, ms = (int(x) for x in m.groups())
                text = " ".join(lines[i + 1:]).strip()
                if text:
                    cues.append((h * 3600 + mi * 60 + s + ms / 1000, re.sub(r"<[^>]+>", "", text)))
                break
    return cues


def segments(cues: list[tuple[float, str]], duration: int | None = None) -> list[dict[str, Any]]:
    """Group cues into ~20-second numbered segments (longer for long videos, to stay under 160)."""
    if not cues:
        return []
    span = max(SEGMENT_SECONDS, int(((duration or cues[-1][0]) / MAX_SEGMENTS) + 1))
    out: list[dict[str, Any]] = []
    for start, text in cues:
        if not out or start - out[-1]["start"] >= span:
            out.append({"start": round(start, 1), "text": text})
        else:
            out[-1]["text"] += " " + text
    for i, s in enumerate(out):
        s["i"] = i
        s["text"] = s["text"][:400]
    return out


async def transcript(yt: YouTubeClient, c: Credentials, video: YtVideo, languages: list[str]) -> list[dict[str, Any]]:
    """The video's subtitles as segments; [] when it has none (chapters are then left out)."""
    if not video.has_captions:
        return []
    try:
        tracks = await yt.captions(c, video.video_id)
        if not tracks:
            return []

        def rank(t: dict[str, Any]) -> tuple[int, int]:
            sn = t.get("snippet") or {}
            lang = (sn.get("language") or "").split("-")[0]
            return (languages.index(lang) if lang in languages else 9, 1 if sn.get("trackKind") == "asr" else 0)

        best = sorted(tracks, key=rank)[0]
        return segments(parse_srt(await yt.caption_text(c, best["id"])), video.duration_s)
    except YouTubeError as e:
        if e.auth:
            raise
        return []


# --- assembling ---


def stamp(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def chapters(picks: list[dict[str, Any]], segs: list[dict[str, Any]], duration: int | None) -> list[dict[str, Any]]:
    """Valid YouTube chapters from the model's segment picks, or [] (timestamps are code's)."""
    if not segs or (duration or 0) < 120:
        return []
    starts: dict[int, str] = {}
    for p in picks:
        if 0 <= p["segment"] < len(segs) and p["segment"] not in starts:
            starts[p["segment"]] = p["title"].strip()[:60]
    ordered = sorted(starts.items())
    if not ordered:
        return []
    ordered[0] = (0, ordered[0][1])  # YouTube requires the first chapter at 0:00
    out: list[dict[str, Any]] = []
    for idx, title in ordered:
        t = 0.0 if idx == 0 else segs[idx]["start"]
        if out and t - out[-1]["seconds"] < MIN_CHAPTER_GAP:
            continue
        if title:
            out.append({"seconds": t, "time": stamp(t), "title": title})
    return out if len(out) >= 3 else []


def clean(text: str) -> str:
    return text.replace("<", "‹").replace(">", "›").strip()  # YouTube refuses < and > in titles and descriptions


def trim_tags(tags: list[str]) -> list[str]:
    """Keep tags in order until YouTube's 500-character limit (multi-word tags count their quotes)."""
    out, total, seen = [], 0, set()
    for t in tags:
        t = clean(t.lstrip("#"))[:100]
        key = t.lower()
        if not t or key in seen:
            continue
        cost = len(t) + (2 if " " in t else 0) + (1 if out else 0)
        if total + cost > TAGS_LIMIT:
            break
        out.append(t)
        seen.add(key)
        total += cost
    return out


def description(body: str, chaps: list[dict[str, Any]], links: str, hashtags: list[str]) -> str:
    parts = [clean(body)]
    if chaps:
        parts.append("\n".join(f"{c['time']} {c['title']}" for c in chaps))
    if links.strip():
        parts.append(clean(links))
    tags = " ".join(f"#{_NOT_HASHTAG.sub('', h)}" for h in hashtags[:5] if h.strip())
    if tags.strip("# "):
        parts.append(tags)
    return "\n\n".join(p for p in parts if p)[:DESCRIPTION_LIMIT]


def seo(titles: list[str], desc: str, tags: list[str], hashtags: list[str], chaps: list[dict[str, Any]],
        translations: int, extra_languages: int) -> dict[str, Any]:
    """Checks computed by code; the score is the share of checks passed."""
    key = (tags[0] if tags else "").lower()
    checks = {
        "title_length_ok": all(len(t) <= 70 for t in titles),
        "keyword_in_title": bool(key) and any(key in t.lower() for t in titles),
        "keyword_early_in_description": bool(key) and key in desc[:200].lower(),
        "description_long_enough": len(desc) >= 250,
        "tags_count_ok": 8 <= len(tags) <= 30,
        "hashtags_ok": 1 <= len(hashtags) <= 5,
        "chapters_ok": bool(chaps),
        "translations_ok": translations >= extra_languages,
    }
    return {"checks": checks, "score": round(sum(checks.values()) / len(checks) * 100), "main_keyword": key or None,
            "title_lengths": [len(t) for t in titles], "tags_chars": sum(len(t) for t in tags), "description_chars": len(desc)}


# --- the work ---


class KitOptions(BaseModel):
    tone: str = Field(default="", max_length=300)
    keywords: str = Field(default="", max_length=300)
    avoid: str = Field(default="", max_length=300)
    languages: list[Literal["az", "ru", "en", "tr"]] | None = None  # default: the channel's


async def start(engine: AsyncEngine, tenant_id: uuid.UUID, connection_id: uuid.UUID, video_id: str, options: KitOptions,
                by: uuid.UUID | None) -> uuid.UUID:
    """A draft row, committed, with its credit spent (raises CreditError first)."""
    from del_social.billing import credits

    did = uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        await credits.spend(db, tenant_id, credits.COST["metadata"], "metadata", did, by)
        db.add(YtDraft(draft_id=did, tenant_id=tenant_id, connection_id=connection_id, video_id=video_id,
                       options=options.model_dump(), created_by=by))
    return did


async def _finish(engine: AsyncEngine, tenant_id: uuid.UUID, did: uuid.UUID, **values: Any) -> None:
    from del_social.billing import credits

    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        d = await db.get(YtDraft, did)
        for k, v in values.items():
            setattr(d, k, v)
        if values.get("status") == "failed":
            await credits.refund(db, tenant_id, did)


async def run(*, engine: AsyncEngine, llm: LLM, yt: YouTubeClient, vault: TokenVault, tenant_id: uuid.UUID, draft_id: uuid.UUID) -> None:
    studio = await load(engine, tenant_id)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            draft = await db.get(YtDraft, draft_id)
            video = await db.get(YtVideo, (studio.connection_id, draft.video_id))
            best = sorted(await sync.videos_of(db, studio), key=lambda v: v.views or 0, reverse=True)[:5]
        if video is None:
            raise YouTubeError("This video is not on the channel (sync again)")
        opts = KitOptions.model_validate(draft.options)
        langs = opts.languages or studio.settings.languages
        segs = await transcript(yt, creds(vault, studio), video, langs)
        channel = studio.channel_block() | {"best_titles": [v.title for v in best]}
        text = (
            f"<channel>\n{reports.dumps(channel)}\n</channel>\n"
            f"<video>\n{reports.dumps({'title': video.title, 'description': video.description[:3000], 'minutes': round((video.duration_s or 0) / 60, 1), 'short': video.is_short, 'current_tags': video.tags[:30]})}\n</video>\n"
            f"<segments>\n{reports.dumps([{'i': s['i'], 'text': s['text']} for s in segs])}\n</segments>\n"
            f"<languages>{', '.join(langs)}</languages>\n"
            f"<options>\n{reports.dumps(opts.model_dump(exclude={'languages'}) | {'links_to_keep': studio.settings.links})}\n</options>"
        )
        result = await agents.metadata(llm, tenant_id, text)
        kit = result.output
        chaps = chapters([c.model_dump() for c in kit.chapters], segs, video.duration_s)
        tags = trim_tags(kit.tags)
        desc = description(kit.description, chaps, studio.settings.links, kit.hashtags)
        titles = [clean(t.text)[:TITLE_LIMIT] for t in kit.titles]
        output = kit.model_dump() | {"titles": [t.model_dump() | {"text": titles[i]} for i, t in enumerate(kit.titles)],
                                     "tags": tags, "final_description": desc, "chapters_timed": chaps,
                                     "segments": len(segs), "cost_usd": str(result.cost_usd or 0)}
        check = seo(titles, desc, tags, kit.hashtags, chaps, len(kit.translations), len(langs) - 1)
        chosen = {"title": titles[0], "description": desc, "tags": tags, "translations": [t.model_dump() for t in kit.translations],
                  "language": langs[0], "comment": kit.pinned_comment}
        await _finish(engine, tenant_id, draft_id, status="ready", output=output, seo=check, chosen=chosen)
    except Exception as e:  # noqa: BLE001
        await _finish(engine, tenant_id, draft_id, status="failed",
                      error=(str(e) if isinstance(e, YouTubeError) else "The kit could not be written; the credit was refunded.")[:500])


class Publish(BaseModel):
    mode: Literal["keep", "public", "unlisted", "private", "schedule"] = "keep"
    at: datetime | None = None  # schedule: when YouTube makes it public


class Chosen(BaseModel):
    """What the owner sends to YouTube (edited from the kit)."""

    title: str = Field(min_length=1, max_length=TITLE_LIMIT)
    description: str = Field(max_length=DESCRIPTION_LIMIT)
    tags: list[str] = Field(default_factory=list, max_length=60)
    translations: list[dict[str, str]] = Field(default_factory=list, max_length=4)
    language: str = Field(default="az", max_length=5)
    comment: str = Field(default="", max_length=1500)
    post_comment: bool = False
    playlist_id: str | None = Field(default=None, max_length=64)
    publish: Publish = Field(default_factory=Publish)


SNIPPET_KEEP = ("categoryId", "defaultAudioLanguage")
STATUS_WRITABLE = ("privacyStatus", "embeddable", "license", "publicStatsViewable", "selfDeclaredMadeForKids", "containsSyntheticMedia")


def video_update(current: dict[str, Any], ch: Chosen, now: datetime) -> tuple[dict[str, Any], str]:
    """The resource for videos.update (full parts, merged with what YouTube has) and its part list."""
    sn = current.get("snippet") or {}
    snippet = {k: sn[k] for k in SNIPPET_KEEP if sn.get(k)} | {
        "title": clean(ch.title)[:TITLE_LIMIT], "description": clean(ch.description)[:DESCRIPTION_LIMIT],
        "tags": trim_tags(ch.tags), "defaultLanguage": sn.get("defaultLanguage") or ch.language,
    }
    snippet.setdefault("categoryId", "22")  # People & Blogs when YouTube returns none
    body: dict[str, Any] = {"id": current["id"], "snippet": snippet}
    parts = ["snippet"]
    if ch.translations:
        loc = dict(current.get("localizations") or {})
        for t in ch.translations:
            if t.get("language") and t.get("language") != snippet["defaultLanguage"]:
                loc[t["language"]] = {"title": clean(t.get("title", ""))[:TITLE_LIMIT], "description": clean(t.get("description", ""))[:DESCRIPTION_LIMIT]}
        body["localizations"] = loc
        parts.append("localizations")
    if ch.publish.mode != "keep":
        st = {k: v for k, v in (current.get("status") or {}).items() if k in STATUS_WRITABLE}
        if ch.publish.mode == "schedule":
            if ch.publish.at is None or ch.publish.at <= now:
                raise ValueError("The publish time must be in the future")
            st |= {"privacyStatus": "private", "publishAt": ch.publish.at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}
        else:
            st["privacyStatus"] = ch.publish.mode
        body["status"] = st
        parts.append("status")
    return body, ",".join(parts)


async def apply(engine: AsyncEngine, yt: YouTubeClient, vault: TokenVault, tenant_id: uuid.UUID, draft_id: uuid.UUID,
                ch: Chosen) -> dict[str, Any]:
    """Write the chosen kit to YouTube. Raises YouTubeError / ValueError with a safe message."""
    studio = await load(engine, tenant_id)
    c = creds(vault, studio)
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        draft = await db.get(YtDraft, draft_id)
    items = await yt.videos(c, [draft.video_id], parts="snippet,status,localizations")
    if not items:
        raise YouTubeError("This video is no longer on the channel")
    body, parts = video_update(items[0], ch, datetime.now(UTC))
    await yt.update_video(c, body, parts)
    done = {"updated": parts.split(",")}
    if ch.post_comment and ch.comment.strip():
        await yt.comment(c, draft.video_id, clean(ch.comment))
        done["comment_posted"] = True
    if ch.playlist_id:
        await yt.add_to_playlist(c, ch.playlist_id, draft.video_id)
        done["playlist"] = ch.playlist_id
    fresh = await yt.videos(c, [draft.video_id])
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        d = await db.get(YtDraft, draft_id)
        d.chosen, d.status, d.applied_at = ch.model_dump(mode="json"), "applied", datetime.now(UTC)
        if fresh:
            row = sync.row_of(fresh[0])
            v = await db.get(YtVideo, (studio.connection_id, draft.video_id))
            for k, val in row.items():
                if k != "video_id":
                    setattr(v, k, val)
    return done
