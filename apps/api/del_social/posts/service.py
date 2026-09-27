"""Posts: build the brief from the photos' analysis, generate captions, revise on request,
publish when approved (now or at the scheduled time).

The model writes language (Copywriter + Brand Guardian); code decides everything else:
which photos, their format and logo, the exact caption that was approved, which accounts
it goes to, when it goes out, and that it goes out only after a person approved it.
Every step reports to the Team Room (live events, wizard steps, messages).
"""
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents import brand_guardian, copywriter
from del_social.agents.brand_guardian import OptionVerdict
from del_social.agents.common import Brief, assemble_caption
from del_social.agents.copywriter import CopyOption
from del_social.agents.pipeline import generate_for_brief
from del_social.connections.base import ChannelError
from del_social.connections.meta import MetaClient
from del_social.connections.meta_publish import publish_facebook, publish_instagram
from del_social.connections.service import credentials
from del_social.core.config import Settings
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault, VaultError
from del_social.knowledge.brand_profile import BrandProfile
from del_social.llm import LLM, LLMError
from del_social.media.storage import signed_url
from del_social.models import BrandProfileVersion, Connection, ConnectionStatus, MediaAsset, Post, Product
from del_social.team import activity
from del_social.team.texts import Msg, m
from del_social.team.timing import baku_label

log = logging.getLogger(__name__)

PUBLISH_URL_TTL = 6 * 3600  # Meta fetches the images while publishing


def publishable(asset: MediaAsset) -> bool:
    return (
        asset.kind == "photo"
        and asset.status == "ready"
        and asset.deleted_at is None
        and asset.source != "reference"
        and (asset.parent_asset_id is None or asset.approved_at is not None)
    )


def _join(parts: list[str], limit: int, sep: str = "; ") -> str:
    out: list[str] = []
    for p in parts:
        p = p.strip()
        if p and p not in out:
            out.append(p)
    return sep.join(out)[:limit]


def build_brief(post_id: uuid.UUID, product: Product | None, assets: list[MediaAsset], notes: str) -> Brief:
    """What the Copywriter gets: the product and what the photos show, from the Photo Analyst."""
    analyses = [a.analysis or {} for a in assets]
    first = analyses[0] if analyses else {}
    name = product.name if product else (first.get("title_az") or "Məhsul")
    hashtags = [h for a in analyses for h in (a.get("hashtags") or [])]
    extra = []
    if notes.strip():
        extra.append(notes.strip())
    seen = [
        f"Photo {i + 1}: " + ", ".join((a.get("features") or []) + (a.get("materials_visible") or []))
        for i, a in enumerate(analyses)
        if a.get("features") or a.get("materials_visible")
    ]
    if seen:
        extra.append(
            "Visible in the photos (from the Photo Analyst; mention only features that do not contradict "
            "each other across photos, and never claim a material that is not listed): " + " | ".join(seen)
        )
    if len(assets) > 1:
        extra.append(f"This is a carousel post with {len(assets)} photos of the same product.")
    if hashtags:
        extra.append("Hashtag ideas from the Photo Analyst: " + " ".join(dict.fromkeys(hashtags)))
    return Brief(
        id=str(post_id)[:8],
        topic=_join([name, first.get("title_az", "")], 500, " — "),
        goal="leads",
        product_category=(first.get("category") or (product.category if product else None) or None),
        photo=_join([a.description or (a.analysis or {}).get("description_az", "") for a in assets], 500),
        key_message=None,
        notes=_join(extra, 1000, "\n") or None,
    )


async def _profile(db: AsyncSession) -> BrandProfile:
    row = await db.scalar(select(BrandProfileVersion).order_by(BrandProfileVersion.version.desc()).limit(1))
    return BrandProfile.model_validate(row.data) if row else BrandProfile()


async def _update(engine: AsyncEngine, tenant_id: uuid.UUID, post_id: uuid.UUID, **values: Any) -> None:
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        row = await db.get(Post, post_id)
        for k, v in values.items():
            setattr(row, k, v)


def approval_text(post: Post) -> Msg:
    when = m("post.when_at", when=baku_label(post.scheduled_at)) if post.scheduled_at else m("post.when_now")
    return m("post.ready", when=when)


async def run_generation(*, engine: AsyncEngine, llm: LLM, tenant_id: uuid.UUID, post_id: uuid.UUID) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        post = await db.get(Post, post_id)
        profile = await _profile(db)
    brief = Brief.model_validate(post.brief)
    task_id = post.task_id

    async def on_event(agent: str, kind: str, title: Msg) -> None:
        await activity.event(engine, tenant_id, agent, kind, title, task_id, post_id)
        key = {"copywriter": "copy", "brand_guardian": "guard"}.get(agent)
        if key:
            await activity.step(engine, tenant_id, task_id, key, "running" if kind == "started" else "done")

    await activity.step(engine, tenant_id, task_id, "photos", "done")
    try:
        result = await generate_for_brief(llm, tenant_id, profile, brief, on_event=on_event)
        best = next((i for i, o in enumerate(result["options"]) if o["verdict"] == "pass"), 0)
        await _update(engine, tenant_id, post_id, status="ready", generation=result, error=None,
                      chosen_option=best, caption=result["options"][best]["caption"])
        await activity.step(engine, tenant_id, task_id, "approval", "waiting", task_status="waiting_approval")
        await activity.say(engine, tenant_id, "team_lead", approval_text(post), task_id, post_id)
    except LLMError as e:
        await _update(engine, tenant_id, post_id, status="failed", error=str(e))
        await activity.step(engine, tenant_id, task_id, "copy", "failed", task_status="failed", note=str(e))
        await activity.event(engine, tenant_id, "copywriter", "failed", m("copy.failed", error=e), task_id, post_id)
        await activity.say(engine, tenant_id, "team_lead", m("copy.failed", error=e), task_id)
    except Exception:
        log.exception("post generation %s failed", post_id)
        await _update(engine, tenant_id, post_id, status="failed", error="Unexpected error while writing the captions")
        await activity.step(engine, tenant_id, task_id, "copy", "failed", task_status="failed")
        await activity.say(engine, tenant_id, "team_lead", m("copy.crashed"), task_id)


async def revise(*, engine: AsyncEngine, llm: LLM, tenant_id: uuid.UUID, post_id: uuid.UUID, instruction: str) -> None:
    """A person says what to change; the Copywriter rewrites the chosen option, the Guardian re-checks."""
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        post = await db.get(Post, post_id)
        profile = await _profile(db)
    brief = Brief.model_validate(post.brief)
    gen = dict(post.generation or {})
    options = list(gen.get("options", []))
    if not options:
        return
    index = post.chosen_option or 0
    current = CopyOption.model_validate({k: options[index][k] for k in CopyOption.model_fields})
    task_id = post.task_id
    await activity.event(engine, tenant_id, "copywriter", "started", m("revise.start", instruction=instruction[:120]), task_id, post_id)
    await activity.step(engine, tenant_id, task_id, "copy", "running")
    try:
        request = brand_guardian.revision_request([(current, OptionVerdict(
            "fix", [{"source": "human", "code": "request", "severity": "fix", "message": f"The approver asks: {instruction}"}]
        ))])
        revised = await copywriter.revise_options(llm, tenant_id, profile, brief, [], request, 1)
        option = revised.output.options[0]
        await activity.event(engine, tenant_id, "copywriter", "finished", m("copy.fixed"), task_id, post_id)
        await activity.event(engine, tenant_id, "brand_guardian", "started", m("guard.rechecking"), task_id, post_id)
        verdicts, _ = await brand_guardian.review(llm, tenant_id, profile, brief, [option])
        verdict = verdicts[0]
        await activity.event(engine, tenant_id, "brand_guardian", "finished",
                             m("guard.pass") if verdict.verdict == "pass" else m("guard.notes"), task_id, post_id)
        caption = assemble_caption(profile, option.caption_az, option.caption_ru, option.hashtags)
        options[index] = {**option.model_dump(), "caption": caption, "verdict": verdict.verdict,
                          "findings": verdict.findings, "revised": True}
        gen["options"] = options
        await _update(engine, tenant_id, post_id, generation=gen, caption=caption, status="ready")
        await activity.step(engine, tenant_id, task_id, "copy", "done")
        await activity.step(engine, tenant_id, task_id, "approval", "waiting", task_status="waiting_approval")
        note = "" if verdict.verdict == "pass" else m("revise.note")
        await activity.say(engine, tenant_id, "copywriter", m("revise.done", instruction=instruction[:200], note=note), task_id, post_id)
    except LLMError as e:
        await activity.event(engine, tenant_id, "copywriter", "failed", m("revise.failed", error=e), task_id, post_id)
        await activity.step(engine, tenant_id, task_id, "copy", "done")
        await activity.say(engine, tenant_id, "copywriter", m("revise.failed", error=e), task_id)


def image_urls(settings: Settings, post: Post, has_logo: bool, ttl: int = PUBLISH_URL_TTL) -> list[str]:
    variant = f"{post.format}-logo" if post.with_logo and has_logo else post.format
    return [signed_url(settings.media_public_url, settings.secret_key, post.tenant_id, a, variant, ttl) for a in post.asset_ids]


async def run_publish(
    *, engine: AsyncEngine, settings: Settings, meta: MetaClient, vault: TokenVault, tenant_id: uuid.UUID,
    post_id: uuid.UUID, has_logo: bool, poll: float = 2.0,
) -> None:
    """Publish to every chosen channel not published yet (safe to retry: never posts twice)."""
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        post = await db.get(Post, post_id)
        conns = {
            c.channel: c
            for c in (await db.scalars(
                select(Connection).where(Connection.status == ConnectionStatus.ACTIVE.value).order_by(Connection.created_at)
            )).all()
        }
    task_id = post.task_id
    await activity.step(engine, tenant_id, task_id, "publish", "running")
    await activity.event(engine, tenant_id, "publisher", "started", m("publish.start", channels=" + ".join(post.channels)), task_id, post_id)
    results: dict[str, Any] = dict(post.results or {})
    urls = image_urls(settings, post, has_logo)
    for channel in post.channels:
        if results.get(channel, {}).get("id"):
            continue  # already out: never publish twice
        conn = conns.get(channel)
        if conn is None:
            results[channel] = {"error": f"No working {channel} connection"}
            continue
        try:
            creds = credentials(vault, conn)
            if channel == "instagram":
                out = await publish_instagram(meta, creds.external_id, creds.token, urls, post.caption or "", poll=poll)
            else:
                out = await publish_facebook(meta, creds.external_id, creds.token, urls, post.caption or "")
            results[channel] = {**out, "account": conn.display_name, "at": datetime.now(UTC).isoformat()}
        except VaultError:
            results[channel] = {"error": "The stored token could not be read. Please connect again."}
        except ChannelError as e:
            results[channel] = {"error": str(e)}
    ok = [c for c in post.channels if results.get(c, {}).get("id")]
    status = "published" if len(ok) == len(post.channels) else ("partly_published" if ok else "approved")
    errors = "; ".join(f"{c}: {results[c]['error']}" for c in post.channels if "error" in results.get(c, {}))
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        row = await db.get(Post, post_id)
        row.results = results
        row.status = status
        row.error = errors or None
        if ok and row.published_at is None:
            row.published_at = datetime.now(UTC)
    links = " · ".join(f"{c}: {results[c].get('url') or results[c]['id']}" for c in ok)
    if status == "published":
        await activity.step(engine, tenant_id, task_id, "publish", "done", task_status="done")
        await activity.event(engine, tenant_id, "publisher", "finished", m("publish.done_event"), task_id, post_id)
        await activity.say(engine, tenant_id, "publisher", m("publish.done", links=links), task_id, post_id)
    else:
        await activity.step(engine, tenant_id, task_id, "publish", "failed", task_status="failed", note=errors)
        await activity.event(engine, tenant_id, "publisher", "failed", m("publish.failed_event", errors=errors), task_id, post_id)
        done = m("publish.partial_done", links=links) if ok else ""
        await activity.say(
            engine, tenant_id, "publisher", m("publish.partial", errors=errors, done=done),
            task_id, post_id,
        )
