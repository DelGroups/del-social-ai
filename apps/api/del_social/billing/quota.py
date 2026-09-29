"""A company's package allowance: what its plan includes this month and how much is used (ADR 007).

Every number here comes from code and the database; no model decides anything. A published post
counts; approved posts waiting for their time are reserved, so they always go out. Drafts are
capped at draft_factor × posts so rejected drafts stay free without being abused. Called inside a
tenant-scoped session (set_tenant), so RLS limits every count to the current company.
"""
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.models import Connection, Invitation, Membership, Plan, Post, Subscription

WARN_AT = 0.8  # share of the allowance that shows a warning
WARN_DAYS = 7  # days before expiry that show a warning
PUBLISHED = ("published", "partly_published")


class QuotaError(ValueError):
    """The package does not allow this (safe to show; the panel answers 402). code: no_plan | expired | posts | drafts | channels | users."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Allowance:
    plan: Plan | None
    subscription: Subscription | None
    period_start: datetime | None
    period_end: datetime | None
    posts_published: int
    posts_scheduled: int
    drafts: int
    channels: int
    users: int  # members + pending invitations
    video_used: int  # stays 0 until the video studio exists (phase 4)
    now: datetime

    @property
    def expired(self) -> bool:
        s = self.subscription
        return bool(s and s.expires_at and s.expires_at <= self.now)

    @property
    def posts_limit(self) -> int | None:
        return self.plan.posts_per_month if self.plan else 0

    @property
    def posts_used(self) -> int:
        return self.posts_published + self.posts_scheduled

    @property
    def drafts_limit(self) -> int | None:
        limit = self.posts_limit
        return None if limit is None else limit * (self.plan.draft_factor if self.plan else 0)

    @property
    def channels_limit(self) -> int | None:
        return self.plan.channels if self.plan else 0

    @property
    def users_limit(self) -> int | None:
        return self.plan.users if self.plan else 0

    @property
    def video_limit(self) -> int | None:
        if not self.plan:
            return 0
        if self.plan.video_credits is None:
            return None
        return self.plan.video_credits + (self.subscription.extra_video_credits if self.subscription else 0)

    @property
    def state(self) -> str:
        """none | expired | limit | warning | ok (what the panel shows)."""
        if self.subscription is None or self.plan is None:
            return "none"
        if self.expired:
            return "expired"
        limit = self.posts_limit
        if limit is not None and self.posts_used >= limit:
            return "limit"
        soon = self.subscription.expires_at and self.subscription.expires_at - self.now <= timedelta(days=WARN_DAYS)
        if soon or (limit is not None and self.posts_used >= WARN_AT * limit):
            return "warning"
        return "ok"


async def allowance(db: AsyncSession, now: datetime | None = None) -> Allowance:
    now = now or datetime.now(UTC)
    sub = await db.scalar(select(Subscription).where(Subscription.status == "active"))
    plan = await db.get(Plan, sub.plan_id) if sub else None
    start = end = None
    published = drafts = 0
    if sub:
        row = (await db.execute(
            text("SELECT period_start, period_end FROM subscription_period(:s, :n)"), {"s": sub.starts_at, "n": now}
        )).one()
        start, end = row.period_start, row.period_end
        published = await db.scalar(select(func.count()).where(
            Post.status.in_(PUBLISHED), Post.published_at >= start, Post.published_at < end
        )) or 0
        drafts = await db.scalar(select(func.count()).where(Post.created_at >= start, Post.created_at < end)) or 0
    scheduled = await db.scalar(select(func.count()).where(Post.status == "scheduled")) or 0
    # A YouTube channel belongs to the YouTube Studio add-on, not to the package (ADR 012)
    channels = await db.scalar(select(func.count()).where(Connection.channel != "youtube")) or 0
    members = await db.scalar(select(func.count()).select_from(Membership)) or 0
    pending = await db.scalar(select(func.count()).where(
        Invitation.accepted_at.is_(None), Invitation.revoked_at.is_(None), Invitation.expires_at > now
    )) or 0
    return Allowance(
        plan=plan, subscription=sub, period_start=start, period_end=end, posts_published=published,
        posts_scheduled=scheduled, drafts=drafts, channels=channels, users=members + pending, video_used=0, now=now,
    )


def _active(a: Allowance) -> None:
    if a.state == "none":
        raise QuotaError("no_plan", "This company has no active package yet. Ask for one on the Package page.")
    if a.expired:
        raise QuotaError("expired", f"The package expired on {a.subscription.expires_at:%d.%m.%Y}. Renew or upgrade it to continue.")


def _posts_left(a: Allowance, exclude: int = 0) -> None:
    limit = a.posts_limit
    if limit is not None and a.posts_used - exclude >= limit:
        raise QuotaError(
            "posts",
            f"All {limit} posts of this month's package are used. Upgrade the package, or new posts can be made from {a.period_end:%d.%m.%Y}.",
        )


async def check_new_post(db: AsyncSession) -> Allowance:
    a = await allowance(db)
    _active(a)
    _posts_left(a)
    if a.drafts_limit is not None and a.drafts >= a.drafts_limit:
        raise QuotaError(
            "drafts",
            f"This month's {a.drafts_limit} drafts are used (3 per post in the package). Approve waiting posts or upgrade the package.",
        )
    return a


async def check_publish(db: AsyncSession, post: Post) -> None:
    """Before approving or publishing now. A retry of a partly published post was already counted."""
    if post.status == "partly_published":
        return
    a = await allowance(db)
    _active(a)
    _posts_left(a, exclude=1 if post.status == "scheduled" else 0)


async def check_new_channel(db: AsyncSession) -> None:
    a = await allowance(db)
    _active(a)
    if a.channels_limit is not None and a.channels >= a.channels_limit:
        raise QuotaError("channels", f"The package includes {a.channels_limit} channels. Upgrade it to connect more.")


async def check_new_member(db: AsyncSession) -> None:
    a = await allowance(db)
    _active(a)
    if a.users_limit is not None and a.users >= a.users_limit:
        raise QuotaError("users", f"The package includes {a.users_limit} users. Upgrade it to invite more people.")
