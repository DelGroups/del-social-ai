"""Brand profile of one tenant: read, save as a new version, browse history (plan §2)."""
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.deps import TenantContext, get_db, require_permission
from del_social.knowledge.brand_profile import BrandProfile
from del_social.models import BrandProfileVersion
from del_social.tenants.permissions import Permission

router = APIRouter(prefix="/tenants/{tenant_id}/brand-profile", tags=["brand"])

can_view = require_permission(Permission.VIEW)
can_edit = require_permission(Permission.MANAGE_BRAND)


class VersionInfo(BaseModel):
    version: int
    created_at: datetime
    created_by_email: str | None  # None if that person has left the company


class BrandProfileOut(BaseModel):
    version: int  # 0 = nothing saved yet; data holds the defaults
    data: BrandProfile
    created_at: datetime | None = None
    created_by_email: str | None = None


class BrandProfileIn(BaseModel):
    base_version: int = Field(ge=0)  # the version the editor started from
    data: BrandProfile


async def _member_emails(db: AsyncSession) -> dict[uuid.UUID, str]:
    rows = (await db.execute(text("SELECT account_id, email FROM auth_tenant_members()"))).all()
    return {r.account_id: r.email for r in rows}


async def _out(db: AsyncSession, row: BrandProfileVersion | None) -> BrandProfileOut:
    if row is None:
        return BrandProfileOut(version=0, data=BrandProfile())
    emails = await _member_emails(db)
    return BrandProfileOut(
        version=row.version,
        data=BrandProfile.model_validate(row.data),
        created_at=row.created_at,
        created_by_email=emails.get(row.created_by),
    )


async def current_profile(db: AsyncSession) -> BrandProfileVersion | None:
    """Latest version for the tenant in scope (RLS), or None."""
    return await db.scalar(
        select(BrandProfileVersion).order_by(BrandProfileVersion.version.desc()).limit(1)
    )


@router.get("", response_model=BrandProfileOut)
async def get_profile(
    ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)
) -> BrandProfileOut:
    return await _out(db, await current_profile(db))


@router.put("", response_model=BrandProfileOut)
async def save_profile(
    body: BrandProfileIn,
    ctx: TenantContext = Depends(can_edit),
    db: AsyncSession = Depends(get_db),
) -> BrandProfileOut:
    latest = await db.scalar(select(func.max(BrandProfileVersion.version))) or 0
    if body.base_version != latest:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Someone saved a newer version meanwhile. Reload and try again."
        )
    row = BrandProfileVersion(
        tenant_id=ctx.tenant_id,
        version=latest + 1,
        data=body.data.model_dump(mode="json"),
        created_by=ctx.account.account_id,
    )
    try:
        async with db.begin_nested():  # two saves at the same moment: one wins, one gets 409
            db.add(row)
            await db.flush()
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Someone saved a newer version meanwhile. Reload and try again."
        ) from None
    await db.refresh(row)
    return await _out(db, row)


@router.get("/versions", response_model=list[VersionInfo])
async def list_versions(
    ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)
) -> list[VersionInfo]:
    rows = (
        await db.scalars(select(BrandProfileVersion).order_by(BrandProfileVersion.version.desc()))
    ).all()
    emails = await _member_emails(db)
    return [
        VersionInfo(version=r.version, created_at=r.created_at, created_by_email=emails.get(r.created_by))
        for r in rows
    ]


@router.get("/versions/{version}", response_model=BrandProfileOut)
async def get_version(
    version: int, ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)
) -> BrandProfileOut:
    row = await db.scalar(select(BrandProfileVersion).where(BrandProfileVersion.version == version))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such version")
    return await _out(db, row)
