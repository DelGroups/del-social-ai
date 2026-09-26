"""Publishes approved posts when their time comes (runs inside the API process).

Every CHECK_SECONDS it asks the database for due posts across tenants through
due_scheduled_posts() (SECURITY DEFINER: returns only tenant and post ids), claims each
one atomically (scheduled → publishing, so it can never go out twice) and publishes it.
The queue worker planned in step 7 can replace this loop without changing anything else.
"""
import asyncio
import logging
import uuid

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.connections.meta import MetaClient
from del_social.core.config import Settings
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault
from del_social.models import MediaAsset, Post
from del_social.posts import service

log = logging.getLogger(__name__)

CHECK_SECONDS = 30


async def publish_due(*, engine: AsyncEngine, settings: Settings, meta: MetaClient, vault: TokenVault, poll: float = 2.0) -> int:
    async with AsyncSession(engine) as db, db.begin():
        due = (await db.execute(text("SELECT tenant_id, post_id FROM due_scheduled_posts()"))).all()
    published = 0
    for tenant_id, post_id in due:
        async with AsyncSession(engine) as db, db.begin():
            await set_tenant(db, tenant_id)
            claimed = await db.execute(
                update(Post).where(Post.post_id == post_id, Post.status == "scheduled").values(status="publishing")
            )
            if claimed.rowcount != 1:
                continue  # someone else took it
            has_logo = await db.scalar(
                select(MediaAsset.asset_id).where(MediaAsset.kind == "logo", MediaAsset.deleted_at.is_(None)).limit(1)
            ) is not None
        await service.run_publish(
            engine=engine, settings=settings, meta=meta, vault=vault, tenant_id=uuid.UUID(str(tenant_id)),
            post_id=uuid.UUID(str(post_id)), has_logo=has_logo, poll=poll,
        )
        published += 1
    return published


async def loop(*, engine: AsyncEngine, settings: Settings, meta: MetaClient, vault: TokenVault) -> None:
    while True:
        try:
            await publish_due(engine=engine, settings=settings, meta=meta, vault=vault)
        except Exception:
            log.exception("scheduled publishing round failed")
        await asyncio.sleep(CHECK_SECONDS)
