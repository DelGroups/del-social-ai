"""media_assets.edit_recipe: each photo's own AI edit settings

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-27

ADR 005 (revised): edits are configured per photo, not switched on per company.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("media_assets", sa.Column("edit_recipe", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("media_assets", "edit_recipe")
