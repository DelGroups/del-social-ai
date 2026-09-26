"""media_assets: tenant photos and logo (files on the media volume)

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-27

docs/phase-1-plan.md §3. Tenant-scoped with forced RLS (ADR 001). del_app has no
DELETE: removing a photo sets deleted_at (the files are removed from disk).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("asset_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("tags", postgresql.ARRAY(sa.Text()), nullable=False, server_default=sa.text("'{}'::text[]")),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("focal_x", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("focal_y", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("enhance", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("uploaded_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('photo', 'logo')", name="ck_media_assets_kind"),
        sa.CheckConstraint("focal_x BETWEEN 0 AND 1 AND focal_y BETWEEN 0 AND 1", name="ck_media_assets_focal"),
    )
    # The same file is stored once per tenant (re-uploads return the existing asset)
    op.create_index(
        "uq_media_assets_tenant_sha", "media_assets", ["tenant_id", "sha256"], unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_media_assets_tenant_created", "media_assets", ["tenant_id", "created_at"])
    op.execute("ALTER TABLE media_assets ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE media_assets FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON media_assets
            USING (tenant_id = app_current_tenant_id())
            WITH CHECK (tenant_id = app_current_tenant_id())
    """)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON media_assets TO {APP_ROLE}")
    op.execute("""
        CREATE TRIGGER fill_tenant_id BEFORE INSERT ON media_assets
            FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()
    """)


def downgrade() -> None:
    op.drop_table("media_assets")
