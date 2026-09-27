"""The team finds competitors on request (ADR 009, revised): a web search dedicated to Instagram
accounts in the company's market, every account verified on Instagram by code, active ones added,
wrong usernames replaced by the real accounts. Also: accounts the owner names in the chat.
Shown live as a workflow; the result comes to the chat in the owner's language.
"""
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.connections.meta import MetaClient
from del_social.connections.service import credentials
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.llm import LLM, load_prompt
from del_social.models import Competitor, Connection
from del_social.research import collect, competitors
from del_social.team import activity, daily
from del_social.team.texts import m

log = logging.getLogger(__name__)

HUNT_STEPS = [
    {"key": "search", "agent": "market_researcher"},
    {"key": "verify", "agent": "market_researcher"},
    {"key": "deliver", "agent": "market_researcher"},
]
MAX_ADDED = 15
SEARCHES = 8


def _names(accounts: list[dict[str, Any]]) -> str:
    return ", ".join(f"@{a.get('username')} ({a.get('followers') or 0:,})".replace(",", " ") for a in accounts)


async def _instagram(engine: AsyncEngine, vault: TokenVault | None, tenant_id: uuid.UUID):
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        ig = await db.scalar(select(Connection).where(Connection.channel == "instagram").order_by(Connection.status))
    return (credentials(vault, ig), ig.connection_id) if ig is not None and vault is not None else (None, None)


async def run_search(
    *, engine: AsyncEngine, llm: LLM, meta: MetaClient | None, vault: TokenVault | None, tenant_id: uuid.UUID,
) -> None:
    now = datetime.now(UTC)
    task_id = await activity.new_task(engine, tenant_id, "competitors", m("hunt.title"), HUNT_STEPS)

    async def step(key: str, status: str, note: activity.Text | None = None, task_status: str | None = None) -> None:
        await activity.step(engine, tenant_id, task_id, key, status, task_status=task_status, note=note)

    await activity.event(engine, tenant_id, "market_researcher", "started", m("hunt.start"), task_id)
    current = "search"
    try:
        creds, conn_id = await _instagram(engine, vault, tenant_id)
        if meta is None or creds is None:
            raise RuntimeError("Instagram is not connected")
        own = await collect.own_account(meta, creds.external_id, creds.token, now)
        if problem := collect.access_problem(own):
            await daily.mark_connection_error(engine, tenant_id, conn_id, problem)
            raise collect.MetaAccessError(problem)
        await daily.mark_connection_ok(engine, tenant_id, conn_id)
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            profile = await daily.profile_of(db)
            known = (await db.scalars(select(Competitor))).all()
        invalid = [c.username for c in known if c.status == "invalid"]
        watched = [c.username for c in known if c.status in ("active", "inactive")]
        b = profile.basics
        request = "\n".join([
            f"Company: {b.company_name}. What it sells: {b.description}",
            f"Product categories: {', '.join(profile.products.categories)}. Cities: {', '.join(b.cities) or 'Baku'}",
            f"Search words: {', '.join(profile.market.keywords) or 'choose yourself'}",
            f"Already watched (don't list again): {', '.join('@' + w for w in watched) or 'none'}",
            f"Named by the owner but not found on Instagram (find their real usernames): {', '.join(invalid) or 'none'}",
            f"You may search at most {SEARCHES} times.",
        ])
        await step("search", "running")
        notes = await llm.research(tenant_id=tenant_id, prompt=load_prompt("competitor_finder"), user=request, max_searches=SEARCHES)
        candidates = competitors.handles_in(notes.text)
        await step("search", "done", m("step.hunt_found", n=len(candidates), sources=len(notes.sources)))

        current = "verify"
        await step("verify", "running")
        words = competitors.relevance_words(profile.products.categories, profile.market.keywords)
        added = await competitors.discover(engine, meta, creds.external_id, creds.token, tenant_id, candidates,
                                           own.get("username"), now, words, limit=MAX_ADDED)
        replaced = await competitors.replace_invalid(engine, tenant_id, added)
        await step("verify", "done", m("step.hunt_verified", added=len(added), checked=len(candidates)))

        current = "deliver"
        still_missing = [n for n in invalid if n not in {old for old, _ in replaced}]
        await activity.say(engine, tenant_id, "market_researcher", m(
            "hunt.result",
            added=m("hunt.added", list=_names(added)) if added else m("hunt.none"),
            replaced=m("hunt.replaced", list=", ".join(f"@{o} → @{n}" for o, n in replaced)) if replaced else "",
            missing=m("hunt.missing", list=", ".join("@" + n for n in still_missing)) if still_missing else "",
        ))
        await step("deliver", "done", m("step.hunt_done", n=len(added)), task_status="done")
        await activity.event(engine, tenant_id, "market_researcher", "finished", m("step.hunt_done", n=len(added)), task_id)
    except collect.MetaAccessError as e:
        await step(current, "failed", str(e)[:120], task_status="failed")
        await activity.say(engine, tenant_id, "market_researcher", m("meta.blocked", error=str(e)[:160]))
    except Exception as e:
        log.exception("competitor search failed for %s", tenant_id)
        await step(current, "failed", str(e)[:120], task_status="failed")
        await activity.event(engine, tenant_id, "market_researcher", "failed", m("hunt.failed", error=str(e)[:200]), task_id)
        await activity.say(engine, tenant_id, "market_researcher", m("hunt.failed", error=str(e)[:200]))


async def run_add(
    *, engine: AsyncEngine, meta: MetaClient | None, vault: TokenVault | None, tenant_id: uuid.UUID, usernames: list[str],
) -> None:
    """Accounts the owner named in the chat: checked on Instagram and watched from now on."""
    creds, conn_id = await _instagram(engine, vault, tenant_id)
    if meta is None or creds is None:
        await activity.say(engine, tenant_id, "market_researcher", m("hunt.failed", error="Instagram is not connected"))
        return
    if problem := collect.access_problem(await collect.own_account(meta, creds.external_id, creds.token, datetime.now(UTC))):
        await daily.mark_connection_error(engine, tenant_id, conn_id, problem)
        await activity.say(engine, tenant_id, "market_researcher", m("meta.blocked", error=problem[:160]))
        return
    added, missing = await competitors.add_given(engine, meta, creds.external_id, creds.token, tenant_id, usernames, datetime.now(UTC))
    await activity.say(engine, tenant_id, "market_researcher", m(
        "hunt.result",
        added=m("hunt.added", list=_names(added)) if added else m("hunt.none"),
        replaced="",
        missing=m("hunt.not_found", list=", ".join("@" + n for n in missing)) if missing else "",
    ))
