"""What the Market Researcher looks at every morning, collected and counted by code (no model).

- Competitors: their public Instagram posts through Meta Business Discovery (official API,
  business/creator accounts only), with likes and comments per post.
- Our own Instagram: recent posts and their engagement, and recent customer comments.
Every number (averages, engagement rates, posts per week, top posts) is computed here, so the
model only reads and interprets them (CLAUDE.md principle 2). Captions and comments are other
people's words: they are passed on as untrusted data, and commenters' names are left out.
"""
import io
import logging
import re
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

import httpx
from PIL import Image

from del_social.connections.meta import MetaClient, MetaError

log = logging.getLogger(__name__)

MEDIA_FIELDS = "caption,like_count,comments_count,timestamp,media_type,permalink,media_url,thumbnail_url"
RECENT = 20  # posts per account
USERNAME = re.compile(r"^[A-Za-z0-9._]{1,30}$")
MAX_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_SIDE = 768  # enough to see models and colours, cheap in tokens


def username_of(entry: str) -> str | None:
    """'@mebel_baku', 'instagram.com/mebel_baku/', 'Mebel Baku (@mebel_baku)' → 'mebel_baku'."""
    s = entry.strip()
    m = re.search(r"instagram\.com/([A-Za-z0-9._]+)", s) or re.search(r"@([A-Za-z0-9._]+)", s)
    name = m.group(1) if m else s
    name = name.strip("/ ").lower()
    return name if USERNAME.match(name) else None


def _ts(value: str | None) -> datetime | None:
    try:
        return datetime.strptime(value or "", "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None


def _post(m: dict[str, Any]) -> dict[str, Any]:
    likes, comments = int(m.get("like_count") or 0), int(m.get("comments_count") or 0)
    return {
        "date": (m.get("timestamp") or "")[:10],
        "type": (m.get("media_type") or "").lower(),
        "likes": likes,
        "comments": comments,
        "caption": re.sub(r"\s+", " ", (m.get("caption") or ""))[:400],
        "permalink": m.get("permalink"),
        "image": m.get("thumbnail_url") if m.get("media_type") == "VIDEO" else m.get("media_url"),
    }


def stats(posts: list[dict[str, Any]], followers: int | None, now: datetime) -> dict[str, Any]:
    """Per-account numbers the model may quote but never computes."""
    dated = [(p, _ts(p.get("at"))) for p in posts]
    week = sum(1 for _, t in dated if t and now - t <= timedelta(days=7))
    month = sum(1 for _, t in dated if t and now - t <= timedelta(days=30))
    avg_likes = round(mean(p["likes"] for p in posts), 1) if posts else 0
    avg_comments = round(mean(p["comments"] for p in posts), 1) if posts else 0
    rate = round((avg_likes + avg_comments) / followers * 100, 2) if followers else None
    types: dict[str, int] = {}
    for p in posts:
        types[p["type"]] = types.get(p["type"], 0) + 1
    return {
        "posts_last_7_days": week, "posts_last_30_days": month, "avg_likes": avg_likes,
        "avg_comments": avg_comments, "engagement_rate_percent": rate, "post_types": types,
    }


def _account(data: dict[str, Any], now: datetime) -> dict[str, Any]:
    raw = (data.get("media") or {}).get("data") or []
    posts = []
    for m in raw[:RECENT]:
        p = _post(m)
        p["at"] = m.get("timestamp")
        posts.append(p)
    followers = data.get("followers_count")
    top = sorted(posts, key=lambda p: p["likes"] + p["comments"], reverse=True)[:3]
    clean = [{k: v for k, v in p.items() if k != "at"} for p in posts]
    return {
        "username": data.get("username"), "name": data.get("name"), "followers": followers,
        "total_posts": data.get("media_count"), "stats": stats(posts, followers, now),
        "top_posts": [{k: v for k, v in p.items() if k != "at"} for p in top], "recent_posts": clean[:12],
    }


async def competitor(meta: MetaClient, ig_user_id: str, token: str, entry: str, now: datetime) -> dict[str, Any]:
    name = username_of(entry)
    if name is None:
        return {"entry": entry[:60], "error": "Not an Instagram username"}
    fields = f"business_discovery.username({name}){{username,name,followers_count,media_count,media.limit({RECENT}){{{MEDIA_FIELDS}}}}}"
    try:
        data = await meta.api(ig_user_id, token, fields=fields)
    except MetaError as e:
        # Personal accounts and wrong names are not visible through Business Discovery
        return {"username": name, "error": str(e)[:200]}
    return _account(data.get("business_discovery") or {}, now)


async def own_account(meta: MetaClient, ig_user_id: str, token: str, now: datetime) -> dict[str, Any]:
    try:
        data = await meta.api(
            ig_user_id, token, fields=f"username,name,followers_count,media_count,media.limit({RECENT}){{id,{MEDIA_FIELDS}}}"
        )
    except MetaError as e:
        return {"error": str(e)[:200]}
    account = _account(data, now)
    # What customers write under our posts in the last two weeks (text only, no names)
    comments: list[dict[str, str]] = []
    for m in ((data.get("media") or {}).get("data") or [])[:8]:
        t = _ts(m.get("timestamp"))
        if not m.get("comments_count") or (t and now - t > timedelta(days=45)):
            continue
        try:
            got = await meta.api(f"{m['id']}/comments", token, fields="text,timestamp", limit="25")
        except MetaError:
            continue
        for c in got.get("data", []):
            ct = _ts(c.get("timestamp"))
            if ct and now - ct <= timedelta(days=14) and c.get("text"):
                comments.append({"date": c["timestamp"][:10], "on_post": (m.get("caption") or "")[:60], "text": c["text"][:300]})
    account["recent_customer_comments"] = comments[:40]
    return account


async def images(http: httpx.AsyncClient, urls: list[str], limit: int = 6) -> list[bytes]:
    """Small JPEGs of the best competitor posts, for the model to see models and colours."""
    out: list[bytes] = []
    for url in urls:
        if len(out) >= limit:
            break
        if not url or not url.startswith("https://"):
            continue
        try:
            r = await http.get(url, timeout=20)
            if r.status_code != 200 or len(r.content) > MAX_IMAGE_BYTES:
                continue
            img = Image.open(io.BytesIO(r.content)).convert("RGB")
            img.thumbnail((IMAGE_SIDE, IMAGE_SIDE))
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=80)
            out.append(buf.getvalue())
        except (httpx.HTTPError, OSError, Image.DecompressionBombError):
            continue
    return out


def now_utc() -> datetime:
    return datetime.now(UTC)
