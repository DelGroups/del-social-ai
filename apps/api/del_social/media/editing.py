"""AI photo edits (ADR 005): background, remove objects, enhance, recolour, swap product.

Code decides everything except the pixels: which edits the company allows, the exact
instruction sent to the image model, the rights of the result (source), its cost, and
that a human must approve it before any post uses it. The original is never changed;
every edit is a new asset pointing at its parent.
"""
import enum
import hashlib
import logging
import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.core.config import Settings
from del_social.core.db import set_tenant
from del_social.knowledge.brand_profile import ImageEditing
from del_social.llm import LLM, LLMError, Tier, load_prompt
from del_social.media import images
from del_social.media.fal import FalClient, FalError
from del_social.media.storage import MediaStore, signed_url
from del_social.models import MediaAsset

log = logging.getLogger(__name__)


class EditKind(enum.StrEnum):
    BACKGROUND = "background"
    REMOVE = "remove"
    ENHANCE = "enhance"
    RECOLOR = "recolor"
    SWAP = "swap"


TOGGLE = {  # edit kind → brand profile switch
    EditKind.BACKGROUND: "background",
    EditKind.REMOVE: "remove_objects",
    EditKind.ENHANCE: "enhance",
    EditKind.RECOLOR: "recolor",
    EditKind.SWAP: "swap_product",
}

# USD per output megapixel (fal.ai model pages, checked 2026-09-27); unknown → cost NULL
PRICE_PER_MP = {"fal-ai/flux-2-pro/edit": Decimal("0.03")}

GUARD = (
    "Photorealistic interior photograph with natural, consistent light, perspective and shadows. "
    "No text, letters, logos, watermarks or people anywhere in the image."
)


def allowed(settings: ImageEditing, kind: EditKind) -> bool:
    return getattr(settings, TOGGLE[kind])


def instruction(kind: EditKind, request: str, subject: str, has_reference: bool) -> str:
    """The exact English instruction for the image model. Built by code, per kind."""
    subject = subject or "the main furniture piece"
    ref = " Use the second image only as a style reference." if has_reference else ""
    if kind is EditKind.BACKGROUND:
        body = (
            f"Keep {subject} exactly as it is: same shape, size, position, construction, materials, colour, "
            f"texture and every detail. Replace only the surroundings"
            + (f" with: {request}." if request else " with a room in the style of the second image.")
            + (ref if request else "")
        )
    elif kind is EditKind.REMOVE:
        body = f"Remove {request} from the photo and fill the area naturally so it matches its surroundings. Change nothing else."
    elif kind is EditKind.RECOLOR:
        body = (
            f"Change only the colour or finish of {subject} to: {request}. Keep its exact shape, proportions, "
            "construction, edges, handles and every detail, and keep the rest of the photo unchanged."
        )
    else:  # SWAP
        product = "the product shown in the second image" if has_reference else request
        body = (
            f"Replace {subject} with {product}"
            + (f" ({request})" if has_reference and request else "")
            + ", matching the original's size, position, perspective and lighting. Keep the room and everything else unchanged."
        )
    return f"{body} {GUARD}"


def result_source(kind: EditKind, parent_source: str, reference_source: str | None) -> str:
    """Rights of the edited image. 'reference' (not ours) is never published."""
    if parent_source == "reference":
        return "reference"
    if kind is EditKind.SWAP and reference_source == "reference":
        return "reference"  # someone else's product inserted: inspiration only
    if kind in (EditKind.BACKGROUND, EditKind.RECOLOR, EditKind.SWAP):
        return "render"  # a visualisation, not a photo of a finished project
    return parent_source


class TranslatedRequest(BaseModel):
    english: str = Field(description="The request translated to concise English, meaning unchanged")


async def to_english(llm: LLM | None, tenant_id: uuid.UUID, request: str) -> str:
    """Users write in Azerbaijani, Russian or Persian; image models follow English best."""
    if llm is None or request.isascii():
        return request
    try:
        r = await llm.structured(
            tenant_id=tenant_id,
            prompt=load_prompt("image_request"),
            user=f"<request>\n{request}\n</request>",
            output=TranslatedRequest,
            tier=Tier.FAST,  # reading and translating to English only; it never writes Azerbaijani
            max_tokens=1000,
        )
        return r.output.english
    except LLMError:
        log.warning("image request translation failed; sending the original text")
        return request


async def run_edit(
    *,
    engine: AsyncEngine,
    settings: Settings,
    fal: FalClient,
    llm: LLM | None,
    store: MediaStore,
    tenant_id: uuid.UUID,
    child_id: uuid.UUID,
) -> None:
    """Background job: produce the edited image for a pending child asset."""

    async def load() -> MediaAsset:
        async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
            await set_tenant(db, tenant_id)
            return await db.get(MediaAsset, child_id)

    async def finish(**values: Any) -> None:
        async with AsyncSession(engine) as db, db.begin():
            await set_tenant(db, tenant_id)
            row = await db.get(MediaAsset, child_id)
            edit = dict(row.edit or {})
            edit.update(values.pop("edit", {}))
            row.edit = edit
            for k, v in values.items():
                setattr(row, k, v)

    child = await load()
    edit = child.edit or {}
    kind = EditKind(edit["kind"])
    try:
        url = lambda asset_id: signed_url(settings.media_public_url, settings.secret_key, tenant_id, asset_id, "full")  # noqa: E731
        image_urls = [url(child.parent_asset_id)]
        if edit.get("reference_asset_id"):
            image_urls.append(url(uuid.UUID(edit["reference_asset_id"])))
        if kind is EditKind.ENHANCE:
            model = settings.image_enhance_model
            payload: dict[str, Any] = {"image_url": image_urls[0], "upscale_factor": 2, "output_format": "jpeg"}
            prompt = None
        else:
            model = settings.image_edit_model
            request_en = await to_english(llm, tenant_id, edit.get("request", ""))
            prompt = instruction(kind, request_en, edit.get("subject", ""), len(image_urls) > 1)
            payload = {"prompt": prompt, "image_urls": image_urls, "output_format": "jpeg"}
        out = await fal.run(model, payload)
        files = out.get("images") or ([out["image"]] if out.get("image") else [])
        if not files or not files[0].get("url"):
            raise FalError("The image model returned no image")
        data = await fal.download(files[0]["url"], images.MAX_UPLOAD_BYTES)
        info = images.inspect(data)
        store.save_original(tenant_id, child_id, data)
        price = PRICE_PER_MP.get(model)
        cost = (price * Decimal(info.width * info.height) / Decimal(1_000_000)).quantize(Decimal("0.0001")) if price else None
        await finish(
            status="ready", width=info.width, height=info.height, bytes=len(data), format=info.format,
            sha256=hashlib.sha256(data).hexdigest(),
            edit={"model": model, "prompt": prompt, "cost_usd": str(cost) if cost is not None else None},
        )
    except (FalError, images.ImageRejected) as e:
        await finish(status="failed", edit={"error": str(e)})
    except Exception:
        log.exception("image edit %s failed", child_id)
        await finish(status="failed", edit={"error": "Unexpected error while editing"})
