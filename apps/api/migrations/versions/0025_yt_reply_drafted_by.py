"""yt_replies.drafted_by: agent when the community manager drafted it by itself (instant replies)

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-30

Automatic drafts are made one comment at a time as comments arrive; credits are counted over all of
them (1 per 20), so the count needs to know which drafts were automatic.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("yt_replies", sa.Column("drafted_by", sa.Text()))


def downgrade() -> None:
    op.drop_column("yt_replies", "drafted_by")
