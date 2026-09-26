"""Media library of one tenant (upload, tag, frame, delete) and the public signed file route."""
import hashlib
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import any_, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.config import get_settings
from del_social.core.db import set_tenant
from del_social.core.deps import TenantContext, get_db, require_permission
from del_social.media import images
from del_social.media.storage import MediaNotConfigured, MediaStore, signed_url, verify
from del_social.models import MediaAsset
from del_social.tenants.permissions import Permission

router = APIRouter(prefix="/tenants/{tenant_id}/media", tags=["media"])
public_router = APIRouter(tags=["media"])

can_view = require_permission(Permission.VIEW)
can_manage = require_permission(Permission.MANAGE_MEDIA)

Kind = Literal["photo", "logo"]
PUBLIC_VARIANTS = ("thumb", "feed", "square", "feed-logo", "square-logo")


def get_store() -> MediaStore:
    return MediaStore(get_settings().media_root)


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
    created_at: datetime
    urls: dict[str, str]  # signed, valid ~24h: thumb, feed, square (+ -logo variants)


class MediaPatch(BaseModel):
    tags: list[str] | None = Field(default=None, max_length=30)
    description: str | None = Field(default=None, max_length=500)
    focal_x: float | None = Field(default=None, ge=0, le=1)
    focal_y: float | None = Field(default=None, ge=0, le=1)
    enhance: bool | None = None


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
        urls = {v: signed_url(s.media_public_url, s.secret_key, asset.tenant_id, asset.asset_id, v) for v in variants}
    except MediaNotConfigured:
        urls = {}
    return MediaOut.model_validate({**{c: getattr(asset, c) for c in MediaOut.model_fields if c != "urls"}, "urls": urls})


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
    if asset is None or asset.deleted_at is not None:
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
            focal=(asset.focal_x, asset.focal_y), enhance=asset.enhance and asset.kind == "photo", logo_data=logo_data,
        )
        await run_in_threadpool(store.save_variant, path, rendered)
    max_age = max(0, min(exp - int(time.time()), 86400))
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": f"public, max-age={max_age}"})
