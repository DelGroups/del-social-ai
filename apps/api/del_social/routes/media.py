"""Media library of one tenant (upload, tag, frame, delete) and the public signed file route."""
import hashlib
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import any_, literal, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.core.config import get_settings
from del_social.core.db import set_tenant
from del_social.core.deps import TenantContext, get_db, get_engine, get_http, require_permission
from del_social.llm import LLM, build_llm
from del_social.media import editing, images
from del_social.media.fal import FalClient
from del_social.media.storage import MediaNotConfigured, MediaStore, signed_url, verify
from del_social.models import MediaAsset
from del_social.tenants.permissions import Permission

router = APIRouter(prefix="/tenants/{tenant_id}/media", tags=["media"])
public_router = APIRouter(tags=["media"])

can_view = require_permission(Permission.VIEW)
can_manage = require_permission(Permission.MANAGE_MEDIA)

Kind = Literal["photo", "logo"]
Source = Literal["own", "render", "licensed", "reference"]
PUBLIC_VARIANTS = ("thumb", "full", "feed", "square", "feed-logo", "square-logo")
EDIT_FIELDS = ("kinds", "recipe", "error", "cost_usd", "cost_complete", "models")


def get_store() -> MediaStore:
    return MediaStore(get_settings().media_root)


def get_fal(http: httpx.AsyncClient = Depends(get_http)) -> FalClient | None:
    s = get_settings()
    if not s.fal_key:
        return None
    return FalClient(http, s.fal_key, s.image_edit_poll_seconds, s.image_edit_timeout_seconds)


def get_translator(engine: AsyncEngine = Depends(get_engine), http: httpx.AsyncClient = Depends(get_http)) -> LLM | None:
    s = get_settings()
    return build_llm(s, engine, http) if s.anthropic_api_key else None


class MediaOut(BaseModel):
    asset_id: uuid.UUID
    kind: Kind
    filename: str
    width: int
    height: int
    bytes: int
    tags: list[str]
    description: str
    focal_x: float
    focal_y: float
    enhance: bool
    source: Source
    parent_asset_id: uuid.UUID | None
    status: Literal["pending", "ready", "failed"]
    edit: dict | None  # for AI results: kinds, recipe, error, cost_usd, cost_complete, models
    approved_at: datetime | None
    recipe: dict | None  # this photo's saved AI edit settings
    publishable: bool  # ready, not a reference, and (for AI edits) approved by a human
    created_at: datetime
    urls: dict[str, str]  # signed, valid ~24h: thumb, feed, square (+ -logo variants)


class MediaPatch(BaseModel):
    tags: list[str] | None = Field(default=None, max_length=30)
    description: str | None = Field(default=None, max_length=500)
    focal_x: float | None = Field(default=None, ge=0, le=1)
    focal_y: float | None = Field(default=None, ge=0, le=1)
    enhance: bool | None = None
    source: Source | None = None


def _clean_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        t = t.strip().lower()[:40]
        if t and t not in out:
            out.append(t)
    return out[:30]


def _out(asset: MediaAsset, has_logo: bool) -> MediaOut:
    s = get_settings()
    variants = ["thumb", "feed", "square"] + (["feed-logo", "square-logo"] if has_logo else [])
    try:
        urls = (
            {v: signed_url(s.media_public_url, s.secret_key, asset.tenant_id, asset.asset_id, v) for v in variants}
            if asset.status == "ready"
            else {}
        )
    except MediaNotConfigured:
        urls = {}
    publishable = (
        asset.status == "ready"
        and asset.source != "reference"
        and (asset.parent_asset_id is None or asset.approved_at is not None)
    )
    fields = {c: getattr(asset, c) for c in MediaOut.model_fields if c not in ("urls", "publishable", "edit", "recipe")}
    edit = {k: v for k, v in (asset.edit or {}).items() if k in EDIT_FIELDS} if asset.edit else None
    return MediaOut.model_validate(
        {**fields, "edit": edit, "recipe": asset.edit_recipe, "urls": urls, "publishable": publishable}
    )


async def _current_logo(db: AsyncSession) -> MediaAsset | None:
    return await db.scalar(
        select(MediaAsset)
        .where(MediaAsset.kind == "logo", MediaAsset.deleted_at.is_(None))
        .order_by(MediaAsset.created_at.desc())
        .limit(1)
    )


async def _get(db: AsyncSession, asset_id: uuid.UUID) -> MediaAsset:
    asset = await db.get(MediaAsset, asset_id)  # RLS: this tenant only
    if asset is None or asset.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    return asset


@router.get("", response_model=list[MediaOut])
async def list_media(
    kind: Kind | None = None,
    tag: str | None = Query(default=None, max_length=40),
    ctx: TenantContext = Depends(can_view),
    db: AsyncSession = Depends(get_db),
) -> list[MediaOut]:
    q = select(MediaAsset).where(MediaAsset.deleted_at.is_(None)).order_by(MediaAsset.created_at.desc())
    if kind:
        q = q.where(MediaAsset.kind == kind)
    if tag:
        q = q.where(literal(tag.strip().lower()) == any_(MediaAsset.tags))
    assets = (await db.scalars(q)).all()
    has_logo = await _current_logo(db) is not None
    return [_out(a, has_logo) for a in assets]


@router.post("", response_model=MediaOut, status_code=status.HTTP_201_CREATED)
async def upload(
    file: UploadFile = File(...),
    kind: Kind = Form("photo"),
    source: Source = Form("own"),
    description: str = Form("", max_length=500),
    tags: str = Form("", max_length=1000),  # comma-separated
    ctx: TenantContext = Depends(can_manage),
    db: AsyncSession = Depends(get_db),
    store: MediaStore = Depends(get_store),
) -> MediaOut:
    data = await file.read(images.MAX_UPLOAD_BYTES + 1)
    try:
        min_side = images.MIN_LOGO_SIDE if kind == "logo" else images.MIN_SIDE
        info = await run_in_threadpool(images.inspect, data, min_side)
    except images.ImageRejected as e:
        raise HTTPException(422, str(e)) from None
    digest = hashlib.sha256(data).hexdigest()
    existing = await db.scalar(
        select(MediaAsset).where(MediaAsset.sha256 == digest, MediaAsset.deleted_at.is_(None))
    )
    has_logo = await _current_logo(db) is not None
    if existing is not None:
        return _out(existing, has_logo)
    asset = MediaAsset(
        asset_id=uuid.uuid4(),
        tenant_id=ctx.tenant_id,
        kind=kind,
        filename=(file.filename or "upload")[:200],
        format=info.format,
        width=info.width,
        height=info.height,
        bytes=len(data),
        sha256=digest,
        tags=_clean_tags(tags.split(",")),
        description=description.strip(),
        source=source,
        uploaded_by=ctx.account.account_id,
    )
    await run_in_threadpool(store.save_original, ctx.tenant_id, asset.asset_id, data)
    db.add(asset)
    await db.flush()
    await db.refresh(asset)
    return _out(asset, has_logo or kind == "logo")


@router.patch("/{asset_id}", response_model=MediaOut)
async def update(
    asset_id: uuid.UUID,
    body: MediaPatch,
    ctx: TenantContext = Depends(can_manage),
    db: AsyncSession = Depends(get_db),
) -> MediaOut:
    asset = await _get(db, asset_id)
    changes = body.model_dump(exclude_none=True)
    if "tags" in changes:
        changes["tags"] = _clean_tags(changes["tags"])
    if "description" in changes:
        changes["description"] = changes["description"].strip()
    for key, value in changes.items():
        setattr(asset, key, value)
    await db.flush()
    await db.refresh(asset)
    return _out(asset, await _current_logo(db) is not None)


@router.delete("/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(
    asset_id: uuid.UUID,
    ctx: TenantContext = Depends(can_manage),
    db: AsyncSession = Depends(get_db),
    store: MediaStore = Depends(get_store),
) -> None:
    asset = await _get(db, asset_id)
    asset.deleted_at = datetime.now(UTC)
    await db.flush()
    await run_in_threadpool(store.delete, asset.tenant_id, asset.asset_id)


# --- AI edits (ADR 005): configured per photo ---


async def _references(db: AsyncSession, recipe: editing.Recipe) -> dict[uuid.UUID, str]:
    """Reference photos in the recipe → their source. They must be finished photos of this tenant."""
    out: dict[uuid.UUID, str] = {}
    for ref_id in recipe.references():
        ref = await _get(db, ref_id)
        if ref.kind != "photo" or ref.status != "ready":
            raise HTTPException(status.HTTP_409_CONFLICT, "A reference must be a finished photo")
        out[ref_id] = ref.source
    return out


async def _editable(db: AsyncSession, asset_id: uuid.UUID) -> MediaAsset:
    asset = await _get(db, asset_id)
    if asset.kind != "photo" or asset.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only finished photos can be edited")
    return asset


@router.put("/{asset_id}/recipe", response_model=MediaOut)
async def save_recipe(
    asset_id: uuid.UUID,
    recipe: editing.Recipe,
    ctx: TenantContext = Depends(can_manage),
    db: AsyncSession = Depends(get_db),
) -> MediaOut:
    """Save this photo's edit settings without running them."""
    asset = await _editable(db, asset_id)
    await _references(db, recipe)
    asset.edit_recipe = recipe.model_dump(mode="json")
    await db.flush()
    await db.refresh(asset)
    return _out(asset, await _current_logo(db) is not None)


@router.post("/{asset_id}/edits", response_model=MediaOut, status_code=status.HTTP_202_ACCEPTED)
async def apply_recipe(
    asset_id: uuid.UUID,
    recipe: editing.Recipe,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(can_manage),
    db: AsyncSession = Depends(get_db),
    engine: AsyncEngine = Depends(get_engine),
    store: MediaStore = Depends(get_store),
    fal: FalClient | None = Depends(get_fal),
    translator: LLM | None = Depends(get_translator),
) -> MediaOut:
    """Save this photo's settings and make one new version with every enabled edit."""
    if fal is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI image editing is not configured on the server")
    try:
        editing.validate(recipe)
    except editing.RecipeError as e:
        raise HTTPException(422, str(e)) from None
    parent = await _editable(db, asset_id)
    reference_sources = await _references(db, recipe)
    recipe_json = recipe.model_dump(mode="json")
    parent.edit_recipe = recipe_json
    child_id = uuid.uuid4()
    child = MediaAsset(
        asset_id=child_id,
        tenant_id=ctx.tenant_id,
        kind="photo",
        filename=f"{parent.filename} · AI"[:200],
        format="JPEG",
        width=parent.width,
        height=parent.height,
        bytes=0,
        sha256=f"pending:{child_id}",
        tags=list(parent.tags),
        description=parent.description,
        focal_x=parent.focal_x,
        focal_y=parent.focal_y,
        enhance=parent.enhance,
        source=editing.result_source(recipe, parent.source, reference_sources),
        parent_asset_id=parent.asset_id,
        status="pending",
        edit={"kinds": [k.value for k in recipe.kinds()], "recipe": recipe_json},
        uploaded_by=ctx.account.account_id,
    )
    # Committed in its own transaction before the job starts: background tasks run before the
    # request's own transaction (get_db) is committed, so the job would not see the row otherwise.
    async with AsyncSession(engine, expire_on_commit=False) as own, own.begin():
        await set_tenant(own, ctx.tenant_id)
        own.add(child)
        await own.flush()
        await own.refresh(child)
    background.add_task(
        editing.run_edit,
        engine=engine, settings=get_settings(), fal=fal, llm=translator, store=store,
        tenant_id=ctx.tenant_id, child_id=child_id,
    )
    return _out(child, await _current_logo(db) is not None)


@router.post("/{asset_id}/approve", response_model=MediaOut)
async def approve_edit(
    asset_id: uuid.UUID,
    ctx: TenantContext = Depends(can_manage),
    db: AsyncSession = Depends(get_db),
) -> MediaOut:
    """A human confirms the AI edit looks right (product intact, nothing odd) before posts may use it."""
    asset = await _get(db, asset_id)
    if asset.parent_asset_id is None or asset.status != "ready":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only finished AI edits need approval")
    asset.approved_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(asset)
    return _out(asset, await _current_logo(db) is not None)


# --- public, signed ---


def _rev(asset: MediaAsset, logo: MediaAsset | None) -> str:
    """Changes whenever framing, tone or the logo changes, so cached files are never stale."""
    key = f"{asset.focal_x:.4f},{asset.focal_y:.4f},{asset.enhance},{logo.asset_id if logo else ''}"
    return hashlib.sha1(key.encode()).hexdigest()[:10]


@public_router.get("/media/{tenant_id}/{asset_id}/{variant}.jpg", include_in_schema=False)
async def public_file(
    tenant_id: uuid.UUID,
    asset_id: uuid.UUID,
    variant: str,
    exp: int = Query(...),
    sig: str = Query(..., max_length=64),
    db: AsyncSession = Depends(get_db),
    store: MediaStore = Depends(get_store),
) -> FileResponse:
    s = get_settings()
    try:
        ok = variant in PUBLIC_VARIANTS and verify(s.secret_key, tenant_id, asset_id, variant, exp, sig)
    except MediaNotConfigured:
        ok = False
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")  # same answer for every failure
    await set_tenant(db, tenant_id)  # the signature is the authorisation
    asset = await db.get(MediaAsset, asset_id)
    if asset is None or asset.deleted_at is not None or asset.status != "ready":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    base, _, with_logo = variant.partition("-")
    logo = await _current_logo(db) if with_logo else None
    if with_logo and logo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    path: Path = store.variant_path(tenant_id, asset_id, variant, _rev(asset, logo))
    if not path.exists():
        original = await run_in_threadpool(store.read_original, tenant_id, asset_id)
        logo_data = await run_in_threadpool(store.read_original, tenant_id, logo.asset_id) if logo else None
        rendered = await run_in_threadpool(
            images.render, original, base,
            focal=(asset.focal_x, asset.focal_y),
            enhance=asset.enhance and asset.kind == "photo" and base != "full",
            logo_data=logo_data,
        )
        await run_in_threadpool(store.save_variant, path, rendered)
    max_age = max(0, min(exp - int(time.time()), 86400))
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": f"public, max-age={max_age}"})
