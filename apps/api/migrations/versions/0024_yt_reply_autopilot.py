"""yt_replies: who sent a reply and why the agent held one back (comment autopilot)

Revision ID: 0024
Revises: 0023
Create Date: 2026-09-30

sent_by: person | agent. hold: why a draft waits for a person even in automatic mode
(check = the agent asked for a look, link, old, limit). Same table, same RLS and grants.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("yt_replies", sa.Column("sent_by", sa.Text()))
    op.add_column("yt_replies", sa.Column("hold", sa.Text()))


def downgrade() -> None:
    op.drop_column("yt_replies", "hold")
    op.drop_column("yt_replies", "sent_by")
