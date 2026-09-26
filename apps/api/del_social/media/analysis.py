"""Runs the Photo Analyst on a library photo and applies its findings (code decides what changes).

Applied automatically, never overwriting what a human wrote:
- description (if empty), tags (merged), focal point (if still the default centre);
- product: joins an existing product the analyst is sure is the same piece, otherwise a
  new product is created with the analyst's name for it.
The full analysis (features, colours, hashtags, quality problems, best format) is stored
on the photo for the other agents and the panel.
"""
import asyncio
import logging
import re
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents import media_analyst
from del_social.agents.media_analyst import ExistingProduct
from del_social.core.db import set_tenant
from del_social.knowledge.brand_profile import BrandProfile
from del_social.llm import LLM, LLMError
from del_social.media import images
from del_social.media.storage import MediaStore
from del_social.models import BrandProfileVersion, MediaAsset, Product

log = logging.getLogger(__name__)

MATCH_CONFIDENCE = 0.75
MAX_COVERS = 8
# One analysis at a time per tenant, so photos uploaded together join the same new product
_locks: defaultdict[uuid.UUID, asyncio.Lock] = defaultdict(asyncio.Lock)


LATIN = re.compile(r"[A-Za-zəğıöüşçƏĞİÖÜŞÇ]")
# The ranges below are U+0400–U+04FF (Cyrillic), written as characters
CYRILLIC = re.compile(r"[Ѐ-ӿ]")
HASHTAG_LATIN = re.compile(r"^#[0-9A-Za-z_əğıöüşçƏĞİÖÜŞÇ]{2,40}$")
HASHTAG_CYRILLIC = re.compile(r"^#[0-9_Ѐ-ӿ]{2,40}$")


def _one_script(text: str) -> bool:
    """Latin (incl. Azerbaijani letters) or Cyrillic, never both in one word (e.g. "#şkафкупе")."""
    return not (LATIN.search(text) and CYRILLIC.search(text))


def clean_hashtags(tags: list[str], limit: int) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in tags:
        t = t.strip()
        if (HASHTAG_LATIN.match(t) or HASHTAG_CYRILLIC.match(t)) and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:limit]


def _merge_tags(existing: list[str], new: list[str]) -> list[str]:
    out = list(existing)
    for t in new:
        t = t.strip().lower()[:40]
        if t and t not in out and _one_script(t):
            out.append(t)
    return out[:30]


async def run_analysis(
    *, engine: AsyncEngine, llm: LLM, store: MediaStore, tenant_id: uuid.UUID, asset_id: uuid.UUID
) -> None:
    async with _locks[tenant_id]:
        await _run(engine, llm, store, tenant_id, asset_id)


async def _run(engine: AsyncEngine, llm: LLM, store: MediaStore, tenant_id: uuid.UUID, asset_id: uuid.UUID) -> None:
    async def set_status(**status: Any) -> None:
        """Status changes keep the rest of the analysis (a person's corrections included)."""
        async with AsyncSession(engine) as db, db.begin():
            await set_tenant(db, tenant_id)
            row = await db.get(MediaAsset, asset_id)
            row.analysis = {**(row.analysis or {}), **status}

    await set_status(status="running", error=None)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            asset = await db.get(MediaAsset, asset_id)
            profile_row = await db.scalar(
                select(BrandProfileVersion).order_by(BrandProfileVersion.version.desc()).limit(1)
            )
            products = (await db.scalars(
                select(Product).where(Product.deleted_at.is_(None)).order_by(Product.created_at.desc())
            )).all()
            covers: dict[uuid.UUID, MediaAsset] = {}
            for p in products[:MAX_COVERS]:
                cover = await db.scalar(
                    select(MediaAsset)
                    .where(MediaAsset.product_id == p.product_id, MediaAsset.deleted_at.is_(None),
                           MediaAsset.status == "ready", MediaAsset.asset_id != asset_id)
                    .order_by(MediaAsset.position).limit(1)
                )
                if cover is not None:
                    covers[p.product_id] = cover
        profile = BrandProfile.model_validate(profile_row.data) if profile_row else BrandProfile()

        photo = await asyncio.to_thread(
            images.render, store.read_original(tenant_id, asset_id), "analysis", enhance=False
        )
        cover_images: list[bytes] = []
        existing: list[ExistingProduct] = []
        for p in products:
            index = None
            if p.product_id in covers:
                cover_images.append(await asyncio.to_thread(
                    images.render, store.read_original(tenant_id, covers[p.product_id].asset_id), "thumb", enhance=False
                ))
                index = len(cover_images) + 1  # image 1 is the photo itself
            existing.append(ExistingProduct(
                product_id=str(p.product_id), name=p.name, category=p.category,
                description=p.description, cover_image=index,
            ))

        result = await media_analyst.analyse(llm, tenant_id, profile, photo, existing, cover_images, asset.description)
        a = result.output

        async with AsyncSession(engine) as db, db.begin():
            await set_tenant(db, tenant_id)
            row = await db.get(MediaAsset, asset_id)
            if not row.description.strip():
                row.description = a.description_az.strip()[:500]
            row.tags = _merge_tags(row.tags, a.tags)
            if row.focal_x == 0.5 and row.focal_y == 0.5:
                row.focal_x = min(1.0, max(0.0, a.focal_x))
                row.focal_y = min(1.0, max(0.0, a.focal_y))
            product_action = None
            if row.product_id is None and row.kind == "photo" and a.is_furniture:
                known = {str(p.product_id) for p in products}
                if a.product_match in known and a.product_match_confidence >= MATCH_CONFIDENCE:
                    row.product_id = uuid.UUID(a.product_match)
                    product_action = "joined"
                else:
                    new = Product(
                        product_id=uuid.uuid4(), tenant_id=tenant_id, name=a.title_az.strip()[:200] or "Məhsul",
                        category=a.category.strip()[:200], description=a.description_az.strip()[:1000],
                    )
                    db.add(new)
                    await db.flush()
                    row.product_id = new.product_id
                    product_action = "created"
                last = await db.scalar(
                    select(func.max(MediaAsset.position)).where(
                        MediaAsset.product_id == row.product_id, MediaAsset.deleted_at.is_(None),
                        MediaAsset.asset_id != asset_id,
                    )
                )
                row.position = 0 if last is None else last + 1
            findings = a.model_dump(mode="json")
            findings["hashtags"] = clean_hashtags(a.hashtags, min(profile.hashtags.max_per_post, 30))
            previous = row.analysis or {}
            human_fields = previous.get("human_fields", [])
            for field in human_fields:  # a person's correction outranks the model
                findings[field] = previous.get(field)
            findings["human_fields"] = human_fields
            row.analysis = {
                "status": "done",
                **findings,
                "product_action": product_action,
                "cost_usd": str(result.cost_usd) if result.cost_usd is not None else None,
                "prompt": result.trace_id,
            }
            row.analyzed_at = datetime.now(UTC)
    except LLMError as e:
        await set_status(status="failed", error=str(e))
    except Exception:
        log.exception("photo analysis %s failed", asset_id)
        await set_status(status="failed", error="Unexpected error while analysing")
