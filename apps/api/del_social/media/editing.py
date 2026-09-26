"""AI photo edits per photo (ADR 005): each photo has its own recipe of switchable edits.

A recipe says, for one photo, which of the five edits to apply and how: enhance,
remove items, new surroundings, new colour/finish, swap the product. Applying it makes
ONE new version with all enabled edits: the instruction edits go to the editor model
in a single combined instruction, then enhance runs last on its result.

Code decides everything except the pixels: the exact instruction, the rights of the
result (source), its cost, and that a human must approve it before posts use it.
The original never changes; every result is a new asset pointing at its parent.
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
from del_social.llm import LLM, LLMError, Tier, load_prompt
from del_social.media import images
from del_social.media.fal import FalClient, FalError
from del_social.media.storage import MediaStore, signed_url
from del_social.models import MediaAsset

log = logging.getLogger(__name__)


class EditKind(enum.StrEnum):
    ENHANCE = "enhance"
    REMOVE = "remove"
    BACKGROUND = "background"
    RECOLOR = "recolor"
    SWAP = "swap"


class Step(BaseModel):
    on: bool = False
    request: str = Field(default="", max_length=500)  # in any language
    reference_asset_id: uuid.UUID | None = None  # background: style to follow; swap: product to insert


class Recipe(BaseModel):
    """One photo's edit settings. Saved with the photo and reused."""

    subject: str = Field(default="", max_length=200)  # the main product, e.g. "the wardrobe"
    enhance: bool = False
    remove: Step = Field(default_factory=Step)
    background: Step = Field(default_factory=Step)
    recolor: Step = Field(default_factory=Step)
    swap: Step = Field(default_factory=Step)

    def kinds(self) -> list[EditKind]:
        out = [k for k in (EditKind.REMOVE, EditKind.BACKGROUND, EditKind.RECOLOR, EditKind.SWAP) if getattr(self, k).on]
        return out + ([EditKind.ENHANCE] if self.enhance else [])

    def references(self) -> list[uuid.UUID]:
        return [s.reference_asset_id for s in (self.background, self.swap) if s.on and s.reference_asset_id]


class RecipeError(ValueError):
    """Safe to show to the user."""


def validate(recipe: Recipe) -> None:
    if not recipe.kinds():
        raise RecipeError("Turn on at least one edit")
    for kind in (EditKind.REMOVE, EditKind.BACKGROUND, EditKind.RECOLOR, EditKind.SWAP):
        step: Step = getattr(recipe, kind)
        described_by_photo = kind in (EditKind.BACKGROUND, EditKind.SWAP) and step.reference_asset_id is not None
        if step.on and not step.request.strip() and not described_by_photo:
            raise RecipeError(f"Describe the change for: {kind.value}")


# USD per output megapixel (fal.ai model pages, checked 2026-09-27); unknown → not counted, flagged
PRICE_PER_MP = {"fal-ai/flux-2-pro/edit": Decimal("0.03")}

GUARD = (
    "Photorealistic interior photograph with natural, consistent light, perspective and shadows. "
    "No text, letters, logos, watermarks or people anywhere in the image."
)
ORDINAL = {2: "second", 3: "third"}


def instruction(recipe: Recipe, requests: dict[EditKind, str]) -> str:
    """One English instruction for all enabled instruction edits. Built by code."""
    subject = recipe.subject.strip() or "the main furniture piece"
    parts: list[str] = []
    image_no = 1
    ref_of: dict[EditKind, int] = {}
    for kind in (EditKind.BACKGROUND, EditKind.SWAP):  # same order as Recipe.references()
        step: Step = getattr(recipe, kind)
        if step.on and step.reference_asset_id:
            image_no += 1
            ref_of[kind] = image_no

    if recipe.remove.on:
        parts.append(f"Remove {requests[EditKind.REMOVE]} and fill those areas naturally so they match their surroundings.")
    if recipe.swap.on:
        if EditKind.SWAP in ref_of:
            product = f"the product shown in the {ORDINAL[ref_of[EditKind.SWAP]]} image"
            extra = f" ({requests[EditKind.SWAP]})" if requests.get(EditKind.SWAP) else ""
        else:
            product, extra = requests[EditKind.SWAP], ""
        parts.append(
            f"Replace {subject} with {product}{extra}, matching the original's size, position, perspective and lighting."
        )
    if recipe.recolor.on:
        target = "the new product" if recipe.swap.on else subject
        parts.append(
            f"Change only the colour or finish of {target} to: {requests[EditKind.RECOLOR]}. "
            "Keep its exact shape, proportions, construction, edges, handles and every detail."
        )
    if recipe.background.on:
        style = (
            f" in the style of the room in the {ORDINAL[ref_of[EditKind.BACKGROUND]]} image"
            if EditKind.BACKGROUND in ref_of
            else ""
        )
        what = requests.get(EditKind.BACKGROUND) or "a new, fitting room"
        parts.append(f"Replace only the surroundings with {what}{style}.")
    if not recipe.swap.on:
        keep = "except for its colour or finish" if recipe.recolor.on else "exactly as it is"
        parts.append(
            f"Keep {subject} {keep}: same shape, size, position, construction, materials, texture and every detail."
        )
    parts.append("Change nothing that was not asked for.")
    return " ".join(parts) + " " + GUARD


def result_source(recipe: Recipe, parent_source: str, reference_sources: dict[uuid.UUID, str]) -> str:
    """Rights of the result. 'reference' (someone else's image) is never published."""
    if parent_source == "reference":
        return "reference"
    swap_ref = recipe.swap.reference_asset_id if recipe.swap.on else None
    if swap_ref and reference_sources.get(swap_ref) == "reference":
        return "reference"  # someone else's product inserted: inspiration only
    if recipe.background.on or recipe.recolor.on or recipe.swap.on:
        return "render"  # a visualisation
    return parent_source


class TranslatedRequest(BaseModel):
    english: str = Field(description="The request translated to concise English, meaning unchanged")


async def to_english(llm: LLM | None, tenant_id: uuid.UUID | None, request: str) -> str:
    """Users write in Azerbaijani, Russian or Persian; image models follow English best."""
    if llm is None or not request or request.isascii():
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


def _first_image(out: dict[str, Any]) -> dict[str, Any]:
    files = out.get("images") or ([out["image"]] if out.get("image") else [])
    if not files or not files[0].get("url"):
        raise FalError("The image model returned no image")
    return files[0]


def _step_cost(model: str, out: dict[str, Any]) -> Decimal | None:
    price = PRICE_PER_MP.get(model)
    if price is None or not out.get("width") or not out.get("height"):
        return None
    return price * Decimal(out["width"] * out["height"]) / Decimal(1_000_000)


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

    async def finish(**values: Any) -> None:
        async with AsyncSession(engine) as db, db.begin():
            await set_tenant(db, tenant_id)
            row = await db.get(MediaAsset, child_id)
            edit = dict(row.edit or {})
            edit.update(values.pop("edit", {}))
            row.edit = edit
            for k, v in values.items():
                setattr(row, k, v)

    async with AsyncSession(engine, expire_on_commit=False) as db, db.begin():
        await set_tenant(db, tenant_id)
        child = await db.get(MediaAsset, child_id)
    recipe = Recipe.model_validate(child.edit["recipe"])

    def url(asset_id: uuid.UUID) -> str:
        return signed_url(settings.media_public_url, settings.secret_key, tenant_id, asset_id, "full")

    try:
        current_url = url(child.parent_asset_id)
        models: list[str] = []
        cost = Decimal(0)
        cost_complete = True
        prompt = None
        instruction_kinds = [k for k in recipe.kinds() if k is not EditKind.ENHANCE]
        steps: list[tuple[str, dict[str, Any]]] = []
        if instruction_kinds:
            requests = {k: await to_english(llm, tenant_id, getattr(recipe, k).request.strip()) for k in instruction_kinds}
            prompt = instruction(recipe, requests)
            refs = [url(r) for r in recipe.references()]
            steps.append((settings.image_edit_model, {"prompt": prompt, "image_urls": [current_url, *refs], "output_format": "jpeg"}))
        if recipe.enhance:
            steps.append((settings.image_enhance_model, {"upscale_factor": 2, "output_format": "jpeg"}))
        for model, payload in steps:
            if "prompt" not in payload:
                payload["image_url"] = current_url  # enhance runs on the previous step's result
            out = _first_image(await fal.run(model, payload))
            models.append(model)
            step_cost = _step_cost(model, out)
            if step_cost is None:
                cost_complete = False
            else:
                cost += step_cost
            current_url = out["url"]  # fal's own URL feeds the next step directly
        data = await fal.download(current_url, images.MAX_UPLOAD_BYTES)
        info = images.inspect(data)
        store.save_original(tenant_id, child_id, data)
        await finish(
            status="ready", width=info.width, height=info.height, bytes=len(data), format=info.format,
            sha256=hashlib.sha256(data).hexdigest(),
            edit={
                "models": models,
                "prompt": prompt,
                "cost_usd": str(cost.quantize(Decimal("0.0001"))),
                "cost_complete": cost_complete,  # False: a model without a known price was used
            },
        )
    except (FalError, images.ImageRejected) as e:
        await finish(status="failed", edit={"error": str(e)})
    except Exception:
        log.exception("image edit %s failed", child_id)
        await finish(status="failed", edit={"error": "Unexpected error while editing"})
