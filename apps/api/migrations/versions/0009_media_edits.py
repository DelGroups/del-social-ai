"""media_assets: source (rights), AI edit lineage, status, approval

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-27

ADR 005. Every photo records where it comes from; "reference" photos (e.g. saved from
Pinterest) are inspiration only and never published. An AI-edited image is a new
asset pointing at its parent, with the edit's details and its own approval.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("media_assets", sa.Column("source", sa.Text(), nullable=False, server_default="own"))
    op.add_column(
        "media_assets",
        sa.Column("parent_asset_id", sa.Uuid(), sa.ForeignKey("media_assets.asset_id", ondelete="RESTRICT")),
    )
    op.add_column("media_assets", sa.Column("edit", postgresql.JSONB()))
    op.add_column("media_assets", sa.Column("status", sa.Text(), nullable=False, server_default="ready"))
    op.add_column("media_assets", sa.Column("approved_at", sa.DateTime(timezone=True)))
    op.create_check_constraint(
        "ck_media_assets_source", "media_assets", "source IN ('own', 'render', 'licensed', 'reference')"
    )
    op.create_check_constraint("ck_media_assets_status", "media_assets", "status IN ('pending', 'ready', 'failed')")
    op.create_index("ix_media_assets_parent", "media_assets", ["parent_asset_id"])


def downgrade() -> None:
    op.drop_index("ix_media_assets_parent", "media_assets")
    op.drop_constraint("ck_media_assets_status", "media_assets")
    op.drop_constraint("ck_media_assets_source", "media_assets")
    for column in ("approved_at", "status", "edit", "parent_asset_id", "source"):
        op.drop_column("media_assets", column)
