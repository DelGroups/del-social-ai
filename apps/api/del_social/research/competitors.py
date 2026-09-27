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
PROFILE_LINK = re.compile(r"instagram\.com/([A-Za-z0-9_](?:[A-Za-z0-9_.]{0,28}[A-Za-z0-9_])?)", re.I)
NOT_COMPANIES = {"instagram", "facebook", "meta", "gmail", "mail", "yahoo", "outlook", "p", "reel", "reels", "explore", "stories", "accounts", "tv"}
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
    """Usernames mentioned in free text (@name or instagram.com/name), in order, without duplicates."""
    found = [*HANDLE.findall(text or ""), *PROFILE_LINK.findall(text or "")]
    return list(dict.fromkeys(h.lower() for h in found if h.lower() not in NOT_COMPANIES))


_FOLLOWERS = re.compile(
    r"(\d[\d.,\s]*\d|\d)\s*([KkMm]|тыс\.?|min)?\s*(?:followers|izləyici|izleyici|подписчик)", re.I
)


def _followers(text: str) -> int | None:
    m = _FOLLOWERS.search(text or "")
    if not m:
        return None
    raw = m.group(1).replace(" ", "")
    mult = {"k": 1_000, "m": 1_000_000, "тыс": 1_000, "тыс.": 1_000, "min": 1_000}.get((m.group(2) or "").lower(), 1)
    if mult > 1:
        raw = raw.replace(",", ".")
    else:
        raw = raw.replace(",", "").replace(".", "")
    try:
        return int(float(raw) * mult)
    except ValueError:
        return None


def web_candidates(text: str) -> list[dict[str, Any]]:
    """Accounts in the web researcher's notes: username, the line it was on, followers if shown."""
    out: dict[str, dict[str, Any]] = {}
    for line in (text or "").splitlines():
        for name in handles_in(line):
            out.setdefault(name, {"username": name, "line": line.strip()[:300], "followers": _followers(line)})
    return list(out.values())


async def add_unverified(
    engine: AsyncEngine, tenant_id: uuid.UUID, candidates: list[dict[str, Any]], own_username: str | None,
    words: set[str], limit: int, now: datetime,
) -> list[dict[str, Any]]:
    """While Meta can't verify: watch accounts from web results that look like this market, as unverified."""
    added = []
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        known = {c.username for c in (await db.scalars(select(Competitor))).all()}
        for cand in candidates:
            if len(added) >= limit:
                break
            name = cand["username"]
            if name in known or name == (own_username or "").lower() or not collect.USERNAME.match(name):
                continue
            text = f"{name} {cand['line']}".lower()
            if not any(w in text for w in words):
                continue  # nothing on the web line says it is this market
            db.add(Competitor(tenant_id=tenant_id, username=name, source="discovered", status="unverified",
                              followers=cand.get("followers"), checked_at=None,
                              note="Found on the web; not yet verified on Instagram"))
            known.add(name)
            added.append(cand)
    return added


def _core(name: str) -> str:
    """The distinctive part of a username or company name, e.g. 'embawood.az' → 'embawood'."""
    s = re.sub(r"[^a-z0-9]", "", (name or "").lower())
    for w in ("azerbaijan", "azerbaycan", "official", "mebeli", "mebel", "mobilya", "furniture", "baku", "baki", "store", "shop",
              "sifarisi", "sifarishi", "sifaris", "sifarish", "online", "ofis", "office", "dizayn", "design", "home", "ev", "az"):
        s = s.replace(w, "")
    return s


def same_company(a: str, b: str) -> bool:
    ca, cb = _core(a), _core(b)
    return len(ca) >= 5 and len(cb) >= 5 and (ca in cb or cb in ca)


def _last_post(account: dict[str, Any]) -> datetime | None:
    dates = [p.get("date") for p in account.get("recent_posts", []) if p.get("date")]
    return datetime.fromisoformat(max(dates) + "T00:00:00+00:00") if dates else None


def _apply(c: Competitor, account: dict[str, Any], now: datetime) -> None:
    c.checked_at = now
    if "error" in account and not account.get("not_found", True):
        c.note = f"Could not be checked: {account['error'][:120]}"  # our access failed; the account may be fine
        return
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
    candidates: list[str], own_username: str | None, now: datetime, words: set[str], limit: int = MAX_NEW_PER_DAY,
) -> list[dict[str, Any]]:
    """Verify usernames found on the web; add real, active business accounts. Returns the new ones."""
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        known = {c.username for c in (await db.scalars(select(Competitor))).all()}
    added: list[dict[str, Any]] = []
    for name in candidates:
        if len(added) >= limit:
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


async def replace_invalid(engine: AsyncEngine, tenant_id: uuid.UUID, found: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """A wrong username the owner gave, whose company the team found under its real username:
    stop watching the wrong one and say which account replaced it. Returns (old, new) pairs."""
    pairs: list[tuple[str, str]] = []
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        for c in (await db.scalars(select(Competitor).where(Competitor.status == "invalid"))).all():
            match = next((a for a in found if same_company(c.username, a.get("username") or "")
                          or same_company(c.username, a.get("name") or "")), None)
            if match:
                c.status = "ignored"
                c.note = f"Replaced by @{match['username']}, the company's real account"
                pairs.append((c.username, match["username"]))
    return pairs


async def add_given(
    engine: AsyncEngine, meta: MetaClient, ig_user_id: str, token: str, tenant_id: uuid.UUID, entries: list[str], now: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Usernames the owner gives in the chat: checked on Instagram, then watched. Returns (added, not found)."""
    added, missing = [], []
    for entry in entries[:10]:
        name = collect.username_of(entry)
        if not name:
            missing.append(entry[:40])
            continue
        account = await collect.competitor(meta, ig_user_id, token, name, now)
        if "error" in account:
            missing.append(name)
            continue
        async with AsyncSession(engine) as db, db.begin():
            await set_tenant(db, tenant_id)
            c = await db.scalar(select(Competitor).where(Competitor.username == name))
            if c is None:
                c = Competitor(tenant_id=tenant_id, username=name, source="owner", status="active")
                db.add(c)
            elif c.status == "ignored":
                c.status = "active"
            c.note = ""
            _apply(c, account, now)
        added.append(account)
    return added, missing
