"""Starting work for the team: the same code path whether a person clicks or the Team Lead decides.

Each start creates a Task (wizard steps shown live) and hands the work to a background job.
"""
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.billing import quota
from del_social.core.db import set_tenant
from del_social.models import MediaAsset, Post, Product, Task
from del_social.posts import service
from del_social.team import activity, texts
from del_social.team.timing import baku_label

Schedule = Callable[..., Any]  # BackgroundTasks.add_task


class WorkError(ValueError):
    """Safe to show (the Team Lead repeats it in the chat)."""


async def select_photos(db: AsyncSession, product_id: uuid.UUID | None, asset_ids: list[uuid.UUID] | None) -> tuple[Product | None, list[MediaAsset]]:
    product = None
    if product_id:
        product = await db.get(Product, product_id)  # RLS: this tenant only
        if product is None or product.deleted_at is not None:
            raise WorkError("Product not found")
    if asset_ids:
        assets = []
        for asset_id in asset_ids:
            asset = await db.get(MediaAsset, asset_id)
            if asset is None or asset.deleted_at is not None:
                raise WorkError("Photo not found")
            assets.append(asset)
        if not all(service.publishable(a) for a in assets):
            raise WorkError(
                "Some photos can't be published: reference images, unfinished photos or AI edits waiting for approval"
            )
    elif product:
        assets = [a for a in (await db.scalars(
            select(MediaAsset).where(MediaAsset.product_id == product.product_id, MediaAsset.deleted_at.is_(None))
            .order_by(MediaAsset.position, MediaAsset.created_at)
        )).all() if service.publishable(a)][:10]
    else:
        raise WorkError("Choose a product or photos")
    if not assets:
        raise WorkError("This product has no publishable photos yet")
    return product, assets


async def start_post(
    *,
    db: AsyncSession,
    engine: AsyncEngine,
    llm: Any,
    schedule: Schedule,
    tenant_id: uuid.UUID,
    account_id: uuid.UUID | None,
    product_id: uuid.UUID | None = None,
    asset_ids: list[uuid.UUID] | None = None,
    fmt: str | None = None,
    with_logo: bool = True,
    channels: list[str] | None = None,
    notes: str = "",
    scheduled_at: datetime | None = None,
) -> Post:
    await quota.check_new_post(db)  # the package must allow another post this month
    product, assets = await select_photos(db, product_id, asset_ids)
    fmt = fmt or ((assets[0].analysis or {}).get("best_format") or "feed")
    post_id, task_id = uuid.uuid4(), uuid.uuid4()
    name = product.name if product else ((assets[0].analysis or {}).get("title_az") or "Post")
    lang = await texts.language_of(db)
    kind = texts.m("post.kind.carousel" if len(assets) > 1 else "post.kind.single").render(lang)
    title = f"{name} · {kind}" + (f" · {baku_label(scheduled_at)}" if scheduled_at else "")
    post = Post(
        post_id=post_id, tenant_id=tenant_id, status="generating", task_id=task_id,
        product_id=product.product_id if product else assets[0].product_id,
        asset_ids=[a.asset_id for a in assets], format=fmt, with_logo=with_logo,
        channels=list(dict.fromkeys(channels or ["instagram", "facebook"])), notes=notes.strip()[:1000],
        brief=service.build_brief(post_id, product, assets, notes).model_dump(mode="json"),
        scheduled_at=scheduled_at, created_by=account_id,
    )
    task = Task(
        task_id=task_id, tenant_id=tenant_id, title=title[:200], kind="post", status="running",
        steps=[{"key": s["key"], "agent": s["agent"], "status": "pending"} for s in activity.POST_STEPS],
        created_by=account_id,
    )
    # Committed in their own transaction before the job starts (background tasks run before get_db commits)
    async with AsyncSession(engine, expire_on_commit=False) as own, own.begin():
        await set_tenant(own, tenant_id)
        own.add(post)
        await own.flush()
        own.add(task)
        await own.flush()
        task.post_id = post_id
        await own.refresh(post)
    await activity.event(engine, tenant_id, "media_analyst", "info", texts.m("photos.picked", n=len(assets), name=name), task_id, post_id)
    schedule(service.run_generation, engine=engine, llm=llm, tenant_id=tenant_id, post_id=post_id)
    return post
