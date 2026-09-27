"""competitors found on the web while Meta can't verify them (ADR 009, web mode)

Revision ID: 0018
Revises: 0017
Create Date: 2026-09-27

status 'unverified': the account was found in web search results (with the follower count the
search result showed, if any) but not checked on Instagram yet, because Meta refused our app.
The next research with Meta access checks it like any other watched account.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_competitors_status", "competitors")
    op.create_check_constraint(
        "ck_competitors_status", "competitors", "status IN ('active', 'invalid', 'inactive', 'ignored', 'unverified')"
    )


def downgrade() -> None:
    op.execute("UPDATE competitors SET status = 'invalid' WHERE status = 'unverified'")
    op.drop_constraint("ck_competitors_status", "competitors")
    op.create_check_constraint("ck_competitors_status", "competitors", "status IN ('active', 'invalid', 'inactive', 'ignored')")
