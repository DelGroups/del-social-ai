"""Posts of one tenant: compose from photos, pick and edit a caption, publish after approval.

Nothing is published without a person pressing Publish (CLAUDE.md principle 5; the
default autonomy policy is human approval).
"""
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.agents.brand_guardian.checks import INSTAGRAM_CAPTION_LIMIT
from del_social.connections.meta import MetaClient
from del_social.core.config import get_settings
from del_social.core.db import set_tenant
from del_social.core.deps import (
    TenantContext, get_db, get_engine, get_meta_optional, get_vault_optional, require_permission,
)
from del_social.core.vault import TokenVault
from del_social.llm import LLM
from del_social.media.storage import MediaNotConfigured, signed_url
from del_social.models import MediaAsset, Post
from del_social.posts import service
from del_social.routes.media import _current_logo, get_analyst
from del_social.routes.products import get_product
from del_social.tenants.permissions import Permission

router = APIRouter(prefix="/tenants/{tenant_id}/posts", tags=["posts"])

can_view = require_permission(Permission.VIEW)
can_approve = require_permission(Permission.APPROVE_CONTENT)

Format = Literal["feed", "square", "landscape"]
ChannelName = Literal["instagram", "facebook"]


class PostIn(BaseModel):
    product_id: uuid.UUID | None = None  # use the product's photos, in their order
    asset_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=10)  # or pick photos
    format: Format | None = None  # default: the Photo Analyst's best format for the first photo
    with_logo: bool = True
    channels: list[ChannelName] = Field(default_factory=lambda: ["instagram", "facebook"], min_length=1)
    notes: str = Field(default="", max_length=1000)  # anything the Copywriter should know


class PostPatch(BaseModel):
    chosen_option: int | None = Field(default=None, ge=0, le=2)
    caption: str | None = Field(default=None, max_length=INSTAGRAM_CAPTION_LIMIT)
    format: Format | None = None
    with_logo: bool | None = None
    channels: list[ChannelName] | None = Field(default=None, min_length=1)
    asset_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=10)  # order; first = cover


class PublishIn(BaseModel):
    confirm: bool  # the panel asks "publish to the live pages now?" and sends true


class PhotoOut(BaseModel):
    asset_id: uuid.UUID
    url: str  # the exact image that will be published (format + logo)


class PostOut(BaseModel):
    post_id: uuid.UUID
    status: str
    product_id: uuid.UUID | None
    format: Format
    with_logo: bool
    channels: list[str]
    notes: str
    photos: list[PhotoOut]
    options: list[dict[str, Any]]  # angle, caption, verdict, findings
    question: str | None
    chosen_option: int | None
    caption: str | None
    error: str | None
    results: dict[str, Any]
    cost_usd: str | None
    approved_at: datetime | None
    published_at: datetime | None
    created_at: datetime


def _out(post: Post, has_logo: bool) -> PostOut:
    s = get_settings()
    variant = f"{post.format}-logo" if post.with_logo and has_logo else post.format
    try:
        photos = [PhotoOut(asset_id=a, url=signed_url(s.media_public_url, s.secret_key, post.tenant_id, a, variant))
                  for a in post.asset_ids]
    except MediaNotConfigured:
        photos = []
    gen = post.generation or {}
    options = [
        {k: o.get(k) for k in ("angle", "caption", "verdict", "findings", "caption_az", "caption_ru", "hashtags")}
        for o in gen.get("options", [])
    ]
    return PostOut(
        post_id=post.post_id, status=post.status, product_id=post.product_id, format=post.format,
        with_logo=post.with_logo, channels=post.channels, notes=post.notes, photos=photos, options=options,
        question=gen.get("question"), chosen_option=post.chosen_option, caption=post.caption, error=post.error,
        results=post.results or {}, cost_usd=gen.get("cost_usd"), approved_at=post.approved_at,
        published_at=post.published_at, created_at=post.created_at,
    )


async def _get(db: AsyncSession, post_id: uuid.UUID) -> Post:
    post = await db.get(Post, post_id)  # RLS: this tenant only
    if post is None or post.status == "archived":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")
    return post


async def _photos(db: AsyncSession, body: PostIn) -> list[MediaAsset]:
    if body.asset_ids:
        assets = []
        for asset_id in body.asset_ids:
            asset = await db.get(MediaAsset, asset_id)
            if asset is None or asset.deleted_at is not None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Photo not found")
            assets.append(asset)
    elif body.product_id:
        await get_product(db, body.product_id)
        assets = list((await db.scalars(
            select(MediaAsset).where(MediaAsset.product_id == body.product_id, MediaAsset.deleted_at.is_(None))
            .order_by(MediaAsset.position, MediaAsset.created_at)
        )).all())
        assets = [a for a in assets if service.publishable(a)][:10]
    else:
        raise HTTPException(422, "Choose a product or photos")
    if not assets:
        raise HTTPException(status.HTTP_409_CONFLICT, "This product has no publishable photos yet")
    blocked = [a for a in assets if not service.publishable(a)]
    if blocked:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Some photos can't be published: reference images, unfinished photos or AI edits waiting for approval",
        )
    return assets


@router.get("", response_model=list[PostOut])
async def list_posts(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> list[PostOut]:
    posts = (await db.scalars(select(Post).where(Post.status != "archived").order_by(Post.created_at.desc()).limit(100))).all()
    has_logo = await _current_logo(db) is not None
    return [_out(p, has_logo) for p in posts]


@router.get("/{post_id}", response_model=PostOut)
async def get_post(post_id: uuid.UUID, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> PostOut:
    return _out(await _get(db, post_id), await _current_logo(db) is not None)


@router.post("", response_model=PostOut, status_code=status.HTTP_202_ACCEPTED)
async def create_post(
    body: PostIn,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(can_approve),
    db: AsyncSession = Depends(get_db),
    engine: AsyncEngine = Depends(get_engine),
    llm: LLM | None = Depends(get_analyst),
) -> PostOut:
    """Start a post: the Copywriter and Brand Guardian write three caption options in the background."""
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The writing agents are not configured on the server")
    assets = await _photos(db, body)
    product = await get_product(db, body.product_id) if body.product_id else None
    fmt = body.format or ((assets[0].analysis or {}).get("best_format") or "feed")
    post_id = uuid.uuid4()
    post = Post(
        post_id=post_id, tenant_id=ctx.tenant_id, status="generating",
        product_id=product.product_id if product else assets[0].product_id,
        asset_ids=[a.asset_id for a in assets], format=fmt, with_logo=body.with_logo,
        channels=list(dict.fromkeys(body.channels)), notes=body.notes.strip(),
        brief=service.build_brief(post_id, product, assets, body.notes).model_dump(mode="json"),
        created_by=ctx.account.account_id,
    )
    # Committed before the job starts (background tasks run before get_db commits)
    async with AsyncSession(engine, expire_on_commit=False) as own, own.begin():
        await set_tenant(own, ctx.tenant_id)
        own.add(post)
        await own.flush()
        await own.refresh(post)
    background.add_task(service.run_generation, engine=engine, llm=llm, tenant_id=ctx.tenant_id, post_id=post_id)
    return _out(post, await _current_logo(db) is not None)


@router.patch("/{post_id}", response_model=PostOut)
async def update_post(
    post_id: uuid.UUID, body: PostPatch, ctx: TenantContext = Depends(can_approve), db: AsyncSession = Depends(get_db)
) -> PostOut:
    post = await _get(db, post_id)
    if post.status not in ("ready", "approved"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This post can't be changed now")
    options = (post.generation or {}).get("options", [])
    if body.chosen_option is not None:
        if body.chosen_option >= len(options):
            raise HTTPException(422, "No such option")
        post.chosen_option = body.chosen_option
        post.caption = options[body.chosen_option]["caption"]
    if body.caption is not None:
        if not body.caption.strip():
            raise HTTPException(422, "The caption is empty")
        post.caption = body.caption.strip()
    if body.asset_ids is not None:
        if len(set(body.asset_ids)) != len(body.asset_ids):
            raise HTTPException(422, "A photo appears twice")
        for asset_id in body.asset_ids:
            asset = await db.get(MediaAsset, asset_id)  # RLS: this tenant only
            if asset is None or not service.publishable(asset):
                raise HTTPException(status.HTTP_409_CONFLICT, "Only publishable photos can be in a post")
        post.asset_ids = list(body.asset_ids)
    for key in ("format", "with_logo", "channels"):
        value = getattr(body, key)
        if value is not None:
            setattr(post, key, list(dict.fromkeys(value)) if key == "channels" else value)
    await db.flush()
    await db.refresh(post)
    return _out(post, await _current_logo(db) is not None)


@router.post("/{post_id}/regenerate", response_model=PostOut, status_code=status.HTTP_202_ACCEPTED)
async def regenerate(
    post_id: uuid.UUID,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(can_approve),
    db: AsyncSession = Depends(get_db),
    engine: AsyncEngine = Depends(get_engine),
    llm: LLM | None = Depends(get_analyst),
) -> PostOut:
    if llm is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The writing agents are not configured on the server")
    post = await _get(db, post_id)
    if post.status not in ("ready", "failed"):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only unpublished posts can be rewritten")
    async with AsyncSession(engine, expire_on_commit=False) as own, own.begin():
        await set_tenant(own, ctx.tenant_id)
        row = await own.get(Post, post_id)
        row.status, row.error = "generating", None
        await own.flush()
        await own.refresh(row)
    background.add_task(service.run_generation, engine=engine, llm=llm, tenant_id=ctx.tenant_id, post_id=post_id)
    return _out(row, await _current_logo(db) is not None)


@router.post("/{post_id}/publish", response_model=PostOut, status_code=status.HTTP_202_ACCEPTED)
async def publish(
    post_id: uuid.UUID,
    body: PublishIn,
    background: BackgroundTasks,
    ctx: TenantContext = Depends(can_approve),
    db: AsyncSession = Depends(get_db),
    engine: AsyncEngine = Depends(get_engine),
    meta: MetaClient | None = Depends(get_meta_optional),
    vault: TokenVault | None = Depends(get_vault_optional),
) -> PostOut:
    """Approve and publish now to the live pages. Retrying publishes only the channels that failed."""
    if not body.confirm:
        raise HTTPException(422, "Publishing needs an explicit confirmation")
    if meta is None or vault is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Publishing is not configured on the server")
    post = await _get(db, post_id)
    if post.status not in ("ready", "approved", "partly_published") or not (post.caption or "").strip():
        raise HTTPException(status.HTTP_409_CONFLICT, "This post is not ready to publish")
    assets = [await db.get(MediaAsset, a) for a in post.asset_ids]
    if not all(a is not None and service.publishable(a) for a in assets):
        raise HTTPException(status.HTTP_409_CONFLICT, "A photo in this post can no longer be published")
    has_logo = await _current_logo(db) is not None
    async with AsyncSession(engine, expire_on_commit=False) as own, own.begin():
        await set_tenant(own, ctx.tenant_id)
        row = await own.get(Post, post_id)
        row.status = "publishing"
        if row.approved_at is None:
            row.approved_by, row.approved_at = ctx.account.account_id, datetime.now(UTC)
        await own.flush()
        await own.refresh(row)
    background.add_task(
        service.run_publish, engine=engine, settings=get_settings(), meta=meta, vault=vault,
        tenant_id=ctx.tenant_id, post_id=post_id, has_logo=has_logo, poll=get_settings().image_edit_poll_seconds,
    )
    return _out(row, has_logo)


@router.post("/{post_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive(post_id: uuid.UUID, ctx: TenantContext = Depends(can_approve), db: AsyncSession = Depends(get_db)) -> None:
    post = await _get(db, post_id)
    if post.status in ("publishing",):
        raise HTTPException(status.HTTP_409_CONFLICT, "Wait until publishing finishes")
    post.status = "archived"
