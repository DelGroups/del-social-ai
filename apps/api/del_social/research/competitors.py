"""The competitors the team watches: the owner's list plus accounts the team finds itself (ADR 009).

Every morning, before the research:
- accounts named in the brand profile are added (source owner);
- each watched account is checked through Meta Business Discovery by code: visible and posting
  (active), not visible (invalid: wrong username or a personal account), or silent for 90 days
  (inactive);
- Instagram usernames the web researcher came across are verified the same way; a business
  account in the company's market that posted in the last 90 days is added (source discovered).
Nothing a model says is taken on trust: a candidate becomes a competitor only if Meta shows it.
"""
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.connections.meta import MetaClient
from del_social.core.db import set_tenant
from del_social.models import Competitor
from del_social.research import collect

MAX_WATCHED = 20
MAX_NEW_PER_DAY = 5
QUIET = timedelta(days=90)
MIN_FOLLOWERS = 200
HANDLE = re.compile(r"(?<![\w.@])@([A-Za-z0-9_](?:[A-Za-z0-9_.]{0,28}[A-Za-z0-9_])?)")
NOT_COMPANIES = {"instagram", "facebook", "meta", "gmail", "mail", "yahoo", "outlook"}
# Always counted as the furniture market, whatever the brand profile says
BASE_WORDS = {"mebel", "мебел", "furniture", "qarderob", "шкаф", "divan", "диван", "mətbəx", "kuxnya", "кухн", "interior", "интерьер"}


def relevance_words(categories: list[str], keywords: list[str]) -> set[str]:
    """Words that show an account sells in the company's market (from the brand profile)."""
    words = set(BASE_WORDS)
    for phrase in [*categories, *keywords]:
        words |= {w.lower() for w in re.findall(r"\w{5,}", phrase)}
    return words


def relevant(account: dict[str, Any], words: set[str]) -> bool:
    text = " ".join([account.get("username") or "", account.get("name") or ""]
                    + [p.get("caption", "") for p in account.get("recent_posts", [])]).lower()
    return any(w in text for w in words)


def handles_in(text: str) -> list[str]:
    """@usernames mentioned in free text (the web notes), in order, without duplicates."""
    return list(dict.fromkeys(h.lower() for h in HANDLE.findall(text or "") if h.lower() not in NOT_COMPANIES))


def _last_post(account: dict[str, Any]) -> datetime | None:
    dates = [p.get("date") for p in account.get("recent_posts", []) if p.get("date")]
    return datetime.fromisoformat(max(dates) + "T00:00:00+00:00") if dates else None


def _apply(c: Competitor, account: dict[str, Any], now: datetime) -> None:
    c.checked_at = now
    if "error" in account:
        c.status = "invalid" if c.status != "ignored" else "ignored"
        c.note = "Not visible to Instagram Business Discovery: check the username or whether it is a business account"
        return
    c.name = account.get("name") or c.name
    c.followers = account.get("followers")
    c.last_post_at = _last_post(account)
    if c.status != "ignored":
        c.status = "active" if c.last_post_at and now - c.last_post_at <= QUIET else "inactive"


async def sync_owner_list(engine: AsyncEngine, tenant_id: uuid.UUID, entries: list[str]) -> None:
    """Accounts the owner named in the brand profile are watched too."""
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        known = {c.username for c in (await db.scalars(select(Competitor))).all()}
        for entry in entries:
            name = collect.username_of(entry)
            if name and name not in known:
                db.add(Competitor(tenant_id=tenant_id, username=name, source="owner", status="active"))
                known.add(name)


async def watched(engine: AsyncEngine, tenant_id: uuid.UUID) -> list[Competitor]:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        return list((await db.scalars(
            select(Competitor).where(Competitor.status != "ignored").order_by(Competitor.source.desc(), Competitor.created_at)
            .limit(MAX_WATCHED)
        )).all())


async def record(engine: AsyncEngine, tenant_id: uuid.UUID, accounts: list[dict[str, Any]], now: datetime) -> None:
    """Store what Business Discovery showed for each watched account."""
    by_name = {(a.get("username") or collect.username_of(a.get("entry", "")) or ""): a for a in accounts}
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        for c in (await db.scalars(select(Competitor))).all():
            if c.username in by_name:
                _apply(c, by_name[c.username], now)


async def discover(
    engine: AsyncEngine, meta: MetaClient, ig_user_id: str, token: str, tenant_id: uuid.UUID,
    candidates: list[str], own_username: str | None, now: datetime, words: set[str],
) -> list[dict[str, Any]]:
    """Verify usernames found on the web; add real, active business accounts. Returns the new ones."""
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        known = {c.username for c in (await db.scalars(select(Competitor))).all()}
    added: list[dict[str, Any]] = []
    for name in candidates:
        if len(added) >= MAX_NEW_PER_DAY:
            break
        if name in known or name == (own_username or "").lower() or not collect.USERNAME.match(name):
            continue
        known.add(name)
        account = await collect.competitor(meta, ig_user_id, token, name, now)
        last = _last_post(account)
        if "error" in account or not last or now - last > QUIET or (account.get("followers") or 0) < MIN_FOLLOWERS:
            continue
        if not relevant(account, words):
            continue  # a real business, but not in this market
        async with AsyncSession(engine) as db, db.begin():
            await set_tenant(db, tenant_id)
            c = Competitor(tenant_id=tenant_id, username=name, source="discovered", status="active",
                           note="Found by the Market Researcher on the web and verified on Instagram")
            _apply(c, account, now)
            db.add(c)
        added.append(account)
    return added
