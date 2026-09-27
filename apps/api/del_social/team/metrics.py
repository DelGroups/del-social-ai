"""What the team can measure, and goals measured against it (ADR 009). Code only: a model may
propose a goal on one of these metrics, but every number (baseline, current, achieved) is ours.
"""
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.core.db import set_tenant
from del_social.models import DailyReport, Goal, Post

# metric → (unit, higher is better)
METRICS: dict[str, tuple[str, bool]] = {
    "followers": ("followers", True),  # Instagram followers
    "engagement_rate": ("%", True),  # (avg likes + comments) / followers, latest 20 Instagram posts
    "avg_likes": ("likes", True),
    "avg_comments": ("comments", True),
    "posts_per_week": ("posts", True),  # our published posts in the last 7 days
}


async def current(db: AsyncSession, now: datetime | None = None) -> dict[str, Decimal | None]:
    """Latest value of every metric: Instagram numbers from the last research, posts from our own data."""
    now = now or datetime.now(UTC)
    report = await db.scalar(select(DailyReport).where(DailyReport.kind == "market", DailyReport.status == "done")
                             .order_by(DailyReport.finished_at.desc()).limit(1))
    own = ((report.input or {}).get("own") or {}) if report else {}
    stats = own.get("stats") or {}

    def num(v: Any) -> Decimal | None:
        return None if v is None else Decimal(str(v)).quantize(Decimal("0.01"))

    week = await db.scalar(select(func.count()).select_from(Post).where(
        Post.status.in_(("published", "partly_published")), Post.published_at >= now - timedelta(days=7)
    )) or 0
    return {
        "followers": num(own.get("followers")),
        "engagement_rate": num(stats.get("engagement_rate_percent")),
        "avg_likes": num(stats.get("avg_likes")),
        "avg_comments": num(stats.get("avg_comments")),
        "posts_per_week": Decimal(week),
    }


def sane_target(metric: str, baseline: Decimal | None, target: float) -> Decimal | None:
    """A target the team can defend: better than now, at most 3× now (or a small absolute number)."""
    if metric not in METRICS or target <= 0:
        return None
    t = Decimal(str(target)).quantize(Decimal("0.01"))
    if baseline is None or baseline <= 0:
        return t if t <= Decimal(10_000) else None
    if t <= baseline or t > baseline * 3:
        return None
    return t


async def update_goals(engine: AsyncEngine, tenant_id: uuid.UUID, today: date) -> list[dict[str, Any]]:
    """Measure active goals; mark achieved or missed. Returns what changed (for the report)."""
    changed = []
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        values = await current(db)
        for g in (await db.scalars(select(Goal).where(Goal.status == "active"))).all():
            v = values.get(g.metric)
            if v is not None:
                g.current = v
            if g.current is not None and g.current >= g.target:
                g.status = "achieved"
                changed.append({"title": g.title, "status": "achieved"})
            elif today > g.due:
                g.status = "missed"
                changed.append({"title": g.title, "status": "missed"})
    return changed


def goal_row(g: Goal) -> dict[str, Any]:
    progress = None
    if g.current is not None and g.baseline is not None and g.target != g.baseline:
        progress = max(0, min(100, int((g.current - g.baseline) / (g.target - g.baseline) * 100)))
    return {
        "goal_id": str(g.goal_id), "title": g.title, "metric": g.metric, "unit": METRICS.get(g.metric, ("", True))[0],
        "baseline": float(g.baseline) if g.baseline is not None else None, "target": float(g.target),
        "current": float(g.current) if g.current is not None else None, "due": g.due.isoformat(),
        "why": g.why, "status": g.status, "progress": progress,
    }
