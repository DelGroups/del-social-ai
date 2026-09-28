"""Every number the YouTube agents read, computed here (CLAUDE.md principle 2).

Analytics (views, watch time, subscribers, traffic, audience, retention) come from the YouTube
Analytics API, which is one to two days behind; "last hours" numbers come from our own snapshots.
A part that YouTube refuses (no revenue on a channel without monetisation, too little data for
demographics) is left out and listed in data_gaps, never guessed.
"""
import statistics
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.connections.base import Credentials
from del_social.connections.youtube import YouTubeClient, YouTubeError, rows_as_dicts
from del_social.models import YtVideo, YtVideoSnapshot

CORE = "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,subscribersLost,likes,comments,shares"


def _r(v: Any, n: int = 1) -> float | int | None:
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() and n == 0 else round(f, n)


class Collector:
    """Runs analytics queries; a refused one becomes a data gap instead of an error."""

    def __init__(self, yt: YouTubeClient, creds: Credentials):
        self.yt, self.creds = yt, creds
        self.gaps: list[str] = []

    async def q(self, what: str, **kw: Any) -> list[dict[str, Any]] | None:
        try:
            return rows_as_dicts(await self.yt.report(self.creds, **kw))
        except YouTubeError as e:
            if e.auth:
                raise
            self.gaps.append(f"{what}: {str(e)[:120]}")
            return None


def _totals(rows: list[dict[str, Any]]) -> dict[str, Any]:
    views = sum(r.get("views") or 0 for r in rows)
    minutes = sum(r.get("estimatedMinutesWatched") or 0 for r in rows)
    gained = sum(r.get("subscribersGained") or 0 for r in rows)
    lost = sum(r.get("subscribersLost") or 0 for r in rows)
    return {
        "views": int(views), "watch_hours": round(minutes / 60, 1),
        "avg_view_seconds": round(minutes * 60 / views) if views else None,
        "subscribers_gained": int(gained), "subscribers_lost": int(lost), "subscribers_net": int(gained - lost),
        "likes": int(sum(r.get("likes") or 0 for r in rows)), "comments": int(sum(r.get("comments") or 0 for r in rows)),
        "shares": int(sum(r.get("shares") or 0 for r in rows)),
    }


def _pct_change(now: float | None, before: float | None) -> float | None:
    if now is None or not before:
        return None
    return round((now - before) / before * 100, 1)


async def daily(c: Collector, today: date) -> dict[str, Any]:
    """The latest day YouTube has data for, compared with the 7 days before it."""
    rows = await c.q("daily numbers", start=today - timedelta(days=12), end=today, metrics=CORE, dimensions="day", sort="day") or []
    rows = [r for r in rows if (r.get("views") or 0) > 0 or (r.get("subscribersGained") or 0) > 0]
    if not rows:
        return {"day": None, "note": "YouTube has no data for the last days yet"}
    last, before = rows[-1], rows[-8:-1]
    avg = {k: round(statistics.mean(r.get(k) or 0 for r in before), 1) for k in ("views", "estimatedMinutesWatched", "subscribersGained")} if before else {}
    day = date.fromisoformat(last["day"])
    top = await c.q("top videos of the day", start=day, end=day, metrics="views,estimatedMinutesWatched,averageViewPercentage",
                    dimensions="video", sort="-views", limit=5) or []
    return {
        "day": last["day"],
        "totals": _totals([last]),
        "average_of_previous_days": {"views": avg.get("views"), "watch_hours": round((avg.get("estimatedMinutesWatched") or 0) / 60, 1),
                                     "subscribers_gained": avg.get("subscribersGained")} if avg else None,
        "views_change_percent": _pct_change(last.get("views"), avg.get("views")),
        "top_videos": [{"video_id": r["video"], "views": int(r.get("views") or 0),
                        "average_view_percent": _r(r.get("averageViewPercentage"))} for r in top],
    }


async def period(c: Collector, start: date, end: date, label: str) -> dict[str, Any]:
    rows = await c.q(f"{label} totals", start=start, end=end, metrics=CORE)
    return {"from": start.isoformat(), "to": end.isoformat(), **(_totals(rows) if rows else {})}


async def breakdowns(c: Collector, start: date, end: date) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if rows := await c.q("traffic sources", start=start, end=end, metrics="views", dimensions="insightTrafficSourceType", sort="-views"):
        total = sum(r["views"] for r in rows) or 1
        out["traffic_sources_percent"] = {r["insightTrafficSourceType"]: round(r["views"] / total * 100, 1) for r in rows[:8]}
    if rows := await c.q("countries", start=start, end=end, metrics="views", dimensions="country", sort="-views", limit=8):
        total = sum(r["views"] for r in rows) or 1
        out["top_countries_percent"] = {r["country"]: round(r["views"] / total * 100, 1) for r in rows}
    if rows := await c.q("age and gender", start=start, end=end, metrics="viewerPercentage", dimensions="ageGroup,gender"):
        out["audience_percent"] = {f"{r['ageGroup']} {r['gender']}": _r(r["viewerPercentage"]) for r in rows if (r.get("viewerPercentage") or 0) >= 1}
    if rows := await c.q("devices", start=start, end=end, metrics="views", dimensions="deviceType", sort="-views"):
        total = sum(r["views"] for r in rows) or 1
        out["devices_percent"] = {r["deviceType"]: round(r["views"] / total * 100, 1) for r in rows}
    return out


async def per_video(c: Collector, start: date, end: date, limit: int = 50) -> dict[str, dict[str, Any]]:
    rows = await c.q("per-video numbers", start=start, end=end, dimensions="video", sort="-views", limit=limit,
                     metrics="views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,subscribersGained,likes,comments") or []
    out = {r["video"]: {"views": int(r.get("views") or 0), "watch_hours": round((r.get("estimatedMinutesWatched") or 0) / 60, 1),
                        "avg_view_seconds": int(r.get("averageViewDuration") or 0),
                        "avg_view_percent": _r(r.get("averageViewPercentage")),
                        "subscribers_gained": int(r.get("subscribersGained") or 0)} for r in rows}
    # Impressions and click-through rate: not available for every channel through the API
    if imp := await c.q("thumbnail impressions", start=start, end=end, dimensions="video", sort="-views", limit=limit,
                        metrics="views,videoThumbnailImpressions,videoThumbnailImpressionsClickRate"):
        for r in imp:
            if r["video"] in out:
                out[r["video"]]["impressions"] = int(r.get("videoThumbnailImpressions") or 0)
                out[r["video"]]["click_rate_percent"] = _r(r.get("videoThumbnailImpressionsClickRate"), 2)
    return out


async def retention(c: Collector, video_id: str, start: date, end: date) -> dict[str, Any] | None:
    """Share of viewers still watching at each point of the video, and where most leave."""
    rows = await c.q(f"retention of {video_id}", start=start, end=end, metrics="audienceWatchRatio",
                     dimensions="elapsedVideoTimeRatio", filters=f"video=={video_id}")
    if not rows:
        return None
    points = [(float(r["elapsedVideoTimeRatio"]), float(r["audienceWatchRatio"])) for r in rows]
    points.sort()
    at = lambda x: next((w for p, w in points if p >= x), points[-1][1])  # noqa: E731
    drops = sorted(((points[i][1] - points[i + 1][1], points[i + 1][0]) for i in range(len(points) - 1)), reverse=True)[:3]
    return {
        "still_watching_percent": {f"{int(x * 100)}%": round(at(x) * 100) for x in (0.1, 0.25, 0.5, 0.75, 0.95)},
        "biggest_drops_at_percent_of_video": [round(p * 100) for _, p in drops],
    }


async def revenue(c: Collector, start: date, end: date) -> dict[str, Any] | None:
    rows = await c.q("revenue (only monetised channels)", start=start, end=end, metrics="estimatedRevenue,playbackBasedCpm")
    if not rows:
        return None
    r = rows[0]
    return {"estimated_revenue_usd": _r(r.get("estimatedRevenue"), 2), "playback_cpm_usd": _r(r.get("playbackBasedCpm"), 2)}


# --- our own numbers ---


def cadence(videos: list[YtVideo], now: datetime) -> dict[str, Any]:
    public = sorted((v.published_at for v in videos if v.published_at and v.privacy in (None, "public")), reverse=True)
    gaps = [(a - b).days for a, b in zip(public, public[1:])][:12]
    return {
        "videos_last_30_days": sum(1 for p in public if now - p <= timedelta(days=30)),
        "videos_last_90_days": sum(1 for p in public if now - p <= timedelta(days=90)),
        "days_since_last_video": (now - public[0]).days if public else None,
        "median_days_between_videos": statistics.median(gaps) if gaps else None,
    }


def formats(videos: list[YtVideo]) -> dict[str, Any]:
    shorts = [v.views or 0 for v in videos if v.is_short]
    longs = [v.views or 0 for v in videos if not v.is_short]
    titles = [len(v.title) for v in videos if v.title]
    return {
        "shorts": {"count": len(shorts), "median_views": statistics.median(shorts) if shorts else None},
        "long_videos": {"count": len(longs), "median_views": statistics.median(longs) if longs else None},
        "median_title_length": statistics.median(titles) if titles else None,
        "median_duration_minutes": round(statistics.median([v.duration_s for v in videos if v.duration_s and not v.is_short]) / 60, 1)
        if any(v.duration_s and not v.is_short for v in videos) else None,
    }


def outlier(views: int | None, usual: list[int]) -> float | None:
    """How many times its channel's usual (median) views a video got."""
    base = statistics.median(usual) if usual else 0
    return round((views or 0) / base, 1) if base else None


async def last_hours(db: AsyncSession, connection_id: Any, hours: int, now: datetime | None = None) -> dict[str, Any]:
    """Views, likes and comments gained per video since `hours` ago, from our snapshots."""
    now = now or datetime.now(UTC)
    since = now - timedelta(hours=hours)
    snaps = (await db.scalars(select(YtVideoSnapshot).where(
        YtVideoSnapshot.connection_id == connection_id, YtVideoSnapshot.at >= now - timedelta(hours=hours + 26),
    ).order_by(YtVideoSnapshot.at))).all()
    videos = {v.video_id: v for v in (await db.scalars(select(YtVideo).where(YtVideo.connection_id == connection_id))).all()}
    by_video: dict[str, list[YtVideoSnapshot]] = {}
    for s in snaps:
        by_video.setdefault(s.video_id, []).append(s)
    rows = []
    for vid, series in by_video.items():
        latest = series[-1]
        base = next((s for s in reversed(series) if s.at <= since), None)
        if base is None or base is latest:
            continue
        gain = (latest.views or 0) - (base.views or 0)
        v = videos.get(vid)
        rows.append({"video_id": vid, "title": v.title if v else vid, "views_gained": gain,
                     "likes_gained": (latest.likes or 0) - (base.likes or 0),
                     "comments_gained": (latest.comments or 0) - (base.comments or 0),
                     "total_views": latest.views, "hours": round((latest.at - base.at).total_seconds() / 3600, 1)})
    rows.sort(key=lambda r: r["views_gained"], reverse=True)
    return {
        "hours": hours, "videos_compared": len(rows),
        "views_gained": sum(r["views_gained"] for r in rows), "comments_gained": sum(r["comments_gained"] for r in rows),
        "rising": [r for r in rows if r["views_gained"] > 0][:5],
    }
