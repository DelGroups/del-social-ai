"""Add-ons and their credits (ADR 012). Every number is computed here from the ledger; no model decides.

- An add-on gives monthly credits for its current monthly window (counted from its start date, the
  same rule as packages). Bought credits never expire.
- Spending takes monthly credits first, then bought ones, and is refused when both are empty.
  Concurrent spending of one company is serialised with a transaction-level advisory lock.
- Work that fails is refunded to the buckets it was paid from.
Called inside a tenant-scoped session (set_tenant): RLS limits every row to the current company.
"""
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.billing.quota import QuotaError
from del_social.models import Addon, Connection, CreditEntry, TenantAddon

YOUTUBE = "youtube"

# What each piece of work costs, in credits (proposal; ADR 012). Cheap text work is 1, AI images 2,
# deep analysis with the strongest model 5. Video work is priced per minute or second of output.
COST = {
    "metadata": 1,  # titles, description, tags, chapters, translations for one video
    "comments": 1,  # reply drafts for up to 20 comments
    "ideas": 3,  # trend research with web search
    "review": 5,  # deep channel review (strongest model)
    "thumbnail_ai": 2,  # one AI background image (text-free)
    "thumbnail_edit": 2,  # one AI edit of a photo or frame
    "cutout": 1,  # background removal of the subject
    "transcribe_10min": 1,  # per started 10 minutes of audio
    "render_min": 1,  # per started minute of rendered video
    "shorts_pick": 1,  # the model picks the best moments of a long video
}


class CreditError(QuotaError):
    """Not enough credits or no add-on (safe to show; the panel answers 402)."""


@dataclass(frozen=True)
class Balance:
    addon: Addon | None
    subscription: TenantAddon | None
    period_start: datetime | None
    period_end: datetime | None
    monthly_limit: int
    monthly_used: int
    purchased: int
    now: datetime

    @property
    def active(self) -> bool:
        s = self.subscription
        return bool(s and (s.expires_at is None or s.expires_at > self.now))

    @property
    def monthly_left(self) -> int:
        return max(0, self.monthly_limit - self.monthly_used)

    @property
    def total(self) -> int:
        return self.monthly_left + max(0, self.purchased)


async def balance(db: AsyncSession, addon_id: str = YOUTUBE, now: datetime | None = None) -> Balance:
    now = now or datetime.now(UTC)
    sub = await db.scalar(select(TenantAddon).where(TenantAddon.addon_id == addon_id, TenantAddon.status == "active"))
    addon = await db.get(Addon, addon_id)
    start = end = None
    used = 0
    if sub:
        row = (await db.execute(
            text("SELECT period_start, period_end FROM subscription_period(:s, :n)"), {"s": sub.starts_at, "n": now}
        )).one()
        start, end = row.period_start, row.period_end
        used = -(await db.scalar(select(func.coalesce(func.sum(CreditEntry.delta), 0)).where(
            CreditEntry.addon_id == addon_id, CreditEntry.bucket == "monthly",
            CreditEntry.created_at >= start, CreditEntry.created_at < end,
        )) or 0)
    purchased = await db.scalar(select(func.coalesce(func.sum(CreditEntry.delta), 0)).where(
        CreditEntry.addon_id == addon_id, CreditEntry.bucket == "purchased",
    )) or 0
    return Balance(
        addon=addon, subscription=sub, period_start=start, period_end=end,
        monthly_limit=addon.monthly_credits if (addon and sub) else 0, monthly_used=max(0, used),
        purchased=int(purchased), now=now,
    )


async def _lock(db: AsyncSession, tenant_id: uuid.UUID, addon_id: str) -> None:
    await db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"credits/{tenant_id}/{addon_id}"})


async def require_addon(db: AsyncSession, addon_id: str = YOUTUBE) -> Balance:
    b = await balance(db, addon_id)
    if b.subscription is None:
        raise CreditError("no_addon", "YouTube Studio is not active for this company. Ask for it on the Package page.")
    if not b.active:
        raise CreditError("addon_expired", f"YouTube Studio expired on {b.subscription.expires_at:%d.%m.%Y}. Renew it to continue.")
    return b


async def require_youtube_channel(db: AsyncSession) -> None:
    """Before connecting another YouTube channel: the add-on is active and has room for it."""
    b = await require_addon(db, YOUTUBE)
    allowed = int((b.addon.features or {}).get("channels", 1)) if b.addon else 1
    n = await db.scalar(select(func.count()).where(Connection.channel == "youtube")) or 0
    if n >= allowed:
        raise CreditError("channels", f"YouTube Studio includes {allowed} channel(s). Disconnect one or ask for more on the Package page.")


async def spend(
    db: AsyncSession, tenant_id: uuid.UUID, amount: int, work: str, ref_id: uuid.UUID | None = None,
    by: uuid.UUID | None = None, addon_id: str = YOUTUBE, note: str = "",
) -> list[CreditEntry]:
    """Take `amount` credits for one piece of work, or raise CreditError. Returns the ledger rows."""
    if amount <= 0:
        return []
    await _lock(db, tenant_id, addon_id)
    b = await require_addon(db, addon_id)
    if b.total < amount:
        raise CreditError(
            "credits",
            f"This needs {amount} credits and {b.total} are left. Buy a credit pack on the Package page"
            + (f", or wait for the new month's credits on {b.period_end:%d.%m.%Y}." if b.period_end else "."),
        )
    from_monthly = min(amount, b.monthly_left)
    rows = []
    for bucket, n in (("monthly", from_monthly), ("purchased", amount - from_monthly)):
        if n:
            row = CreditEntry(entry_id=uuid.uuid4(), tenant_id=tenant_id, addon_id=addon_id, bucket=bucket, delta=-n,
                              reason=f"spend:{work}", ref_id=ref_id, note=note[:200], created_by=by)
            db.add(row)
            rows.append(row)
    await db.flush()
    return rows


async def refund(db: AsyncSession, tenant_id: uuid.UUID, ref_id: uuid.UUID, addon_id: str = YOUTUBE) -> int:
    """Give back everything spent on one job that failed (once). Returns the credits refunded."""
    await _lock(db, tenant_id, addon_id)
    rows = (await db.scalars(select(CreditEntry).where(CreditEntry.ref_id == ref_id, CreditEntry.addon_id == addon_id))).all()
    if any(r.reason == "refund" for r in rows):
        return 0
    b = await balance(db, addon_id)
    total = 0
    for r in rows:
        if r.delta < 0:
            # Monthly credits of a month that has ended come back as bought ones (they would be lost otherwise)
            old = r.bucket == "monthly" and (b.period_start is None or r.created_at < b.period_start)
            db.add(CreditEntry(entry_id=uuid.uuid4(), tenant_id=tenant_id, addon_id=addon_id, bucket="purchased" if old else r.bucket,
                               delta=-r.delta, reason="refund", ref_id=ref_id, note=r.reason))
            total += -r.delta
    await db.flush()
    return total


async def grant(
    db: AsyncSession, tenant_id: uuid.UUID, credits: int, reason: str, by: uuid.UUID | None, note: str = "",
    addon_id: str = YOUTUBE,
) -> CreditEntry:
    """Bought (or given) credits, by the platform admin. They never expire."""
    row = CreditEntry(entry_id=uuid.uuid4(), tenant_id=tenant_id, addon_id=addon_id, bucket="purchased",
                      delta=credits, reason=reason, note=note[:200], created_by=by)
    db.add(row)
    await db.flush()
    return row
