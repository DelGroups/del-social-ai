"""Posts: build the brief from the photos' analysis, generate captions, publish when approved.

The model writes language (Copywriter + Brand Guardian); code decides everything else:
which photos, their format and logo, the exact caption that was approved, which accounts
it goes to, and that it goes out only after a human pressed Publish.
"""
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents.common import Brief
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


async def run_generation(*, engine: AsyncEngine, llm: LLM, tenant_id: uuid.UUID, post_id: uuid.UUID) -> None:
    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        post = await db.get(Post, post_id)
        profile = await _profile(db)
        brief = Brief.model_validate(post.brief)
    try:
        result = await generate_for_brief(llm, tenant_id, profile, brief)
        values: dict[str, Any] = {"status": "ready", "generation": result, "error": None}
        best = next((i for i, o in enumerate(result["options"]) if o["verdict"] == "pass"), 0)
        values |= {"chosen_option": best, "caption": result["options"][best]["caption"]}
    except LLMError as e:
        values = {"status": "failed", "error": str(e)}
    except Exception:
        log.exception("post generation %s failed", post_id)
        values = {"status": "failed", "error": "Unexpected error while writing the captions"}
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        row = await db.get(Post, post_id)
        for k, v in values.items():
            setattr(row, k, v)


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
    async with AsyncSession(engine) as db, db.begin():
        await set_tenant(db, tenant_id)
        row = await db.get(Post, post_id)
        row.results = results
        row.status = status
        row.error = None if status == "published" else "; ".join(
            f"{c}: {results[c]['error']}" for c in post.channels if "error" in results.get(c, {})
        )
        if ok and row.published_at is None:
            row.published_at = datetime.now(UTC)
