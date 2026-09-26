"""products: group several photos of one product; choose the logo used on posts

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-27

A product (e.g. "Wendy wardrobe") holds an ordered set of photos; multi-photo
(carousel) posts are built from it. Tenant-scoped with forced RLS (ADR 001);
del_app has no DELETE (products are soft-deleted).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("product_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_products_tenant", "products", ["tenant_id"])
    op.execute("ALTER TABLE products ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE products FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON products
            USING (tenant_id = app_current_tenant_id())
            WITH CHECK (tenant_id = app_current_tenant_id())
    """)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON products TO {APP_ROLE}")
    op.execute("""
        CREATE TRIGGER fill_tenant_id BEFORE INSERT ON products
            FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()
    """)

    op.add_column(
        "media_assets",
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.product_id", ondelete="RESTRICT")),
    )
    op.add_column("media_assets", sa.Column("position", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("media_assets", sa.Column("default_logo", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.create_index("ix_media_assets_product", "media_assets", ["product_id", "position"])


def downgrade() -> None:
    op.drop_index("ix_media_assets_product", "media_assets")
    for column in ("default_logo", "position", "product_id"):
        op.drop_column("media_assets", column)
    op.drop_table("products")
