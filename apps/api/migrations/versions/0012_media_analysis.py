"""media_assets.analysis: what the Photo Analyst found in each photo

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-27
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("media_assets", sa.Column("analysis", postgresql.JSONB()))
    op.add_column("media_assets", sa.Column("analyzed_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("media_assets", "analyzed_at")
    op.drop_column("media_assets", "analysis")
