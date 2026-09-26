"""Products of one tenant: each groups an ordered set of photos (for multi-photo posts)."""
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.deps import TenantContext, get_db, require_permission
from del_social.models import MediaAsset, Product
from del_social.tenants.permissions import Permission

router = APIRouter(prefix="/tenants/{tenant_id}/products", tags=["products"])

can_view = require_permission(Permission.VIEW)
can_manage = require_permission(Permission.MANAGE_MEDIA)


class ProductIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="", max_length=200)
    description: str = Field(default="", max_length=1000)


class ProductPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=200)
    description: str | None = Field(default=None, max_length=1000)


class ProductOut(BaseModel):
    product_id: uuid.UUID
    name: str
    category: str
    description: str
    photos: int
    created_at: datetime


class OrderIn(BaseModel):
    asset_ids: list[uuid.UUID] = Field(max_length=100)  # the product's photos, first = cover


async def get_product(db: AsyncSession, product_id: uuid.UUID) -> Product:
    product = await db.get(Product, product_id)  # RLS: this tenant only
    if product is None or product.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product


async def _out(db: AsyncSession, product: Product) -> ProductOut:
    count = await db.scalar(
        select(func.count()).where(MediaAsset.product_id == product.product_id, MediaAsset.deleted_at.is_(None))
    )
    return ProductOut(
        product_id=product.product_id, name=product.name, category=product.category,
        description=product.description, photos=count or 0, created_at=product.created_at,
    )


@router.get("", response_model=list[ProductOut])
async def list_products(ctx: TenantContext = Depends(can_view), db: AsyncSession = Depends(get_db)) -> list[ProductOut]:
    products = (
        await db.scalars(select(Product).where(Product.deleted_at.is_(None)).order_by(Product.name))
    ).all()
    return [await _out(db, p) for p in products]


@router.post("", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: ProductIn, ctx: TenantContext = Depends(can_manage), db: AsyncSession = Depends(get_db)
) -> ProductOut:
    product = Product(
        product_id=uuid.uuid4(), tenant_id=ctx.tenant_id,
        name=body.name.strip(), category=body.category.strip(), description=body.description.strip(),
    )
    db.add(product)
    await db.flush()
    await db.refresh(product)
    return await _out(db, product)


@router.patch("/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: uuid.UUID, body: ProductPatch, ctx: TenantContext = Depends(can_manage), db: AsyncSession = Depends(get_db)
) -> ProductOut:
    product = await get_product(db, product_id)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(product, key, value.strip())
    await db.flush()
    await db.refresh(product)
    return await _out(db, product)


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: uuid.UUID, ctx: TenantContext = Depends(can_manage), db: AsyncSession = Depends(get_db)
) -> None:
    """The photos stay in the library, just no longer grouped."""
    product = await get_product(db, product_id)
    await db.execute(update(MediaAsset).where(MediaAsset.product_id == product_id).values(product_id=None, position=0))
    product.deleted_at = datetime.now(UTC)


@router.put("/{product_id}/order", response_model=ProductOut)
async def reorder(
    product_id: uuid.UUID, body: OrderIn, ctx: TenantContext = Depends(can_manage), db: AsyncSession = Depends(get_db)
) -> ProductOut:
    """Set the photo order; the first photo is the cover of a multi-photo post."""
    product = await get_product(db, product_id)
    current = set(
        (await db.scalars(
            select(MediaAsset.asset_id).where(MediaAsset.product_id == product_id, MediaAsset.deleted_at.is_(None))
        )).all()
    )
    if set(body.asset_ids) != current or len(body.asset_ids) != len(current):
        raise HTTPException(status.HTTP_409_CONFLICT, "The order must list exactly this product's photos")
    for position, asset_id in enumerate(body.asset_ids):
        await db.execute(update(MediaAsset).where(MediaAsset.asset_id == asset_id).values(position=position))
    return await _out(db, product)
