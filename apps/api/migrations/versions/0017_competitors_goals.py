"""the team's own knowledge: competitors it watches (and finds), goals it proposes, meetings (ADR 009)

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-27

- competitors: accounts the Market Researcher watches. source = owner (from the brand profile)
  or discovered (found on the web and verified by code through Meta Business Discovery).
  status: active | invalid (not visible to Business Discovery) | inactive (no post for 90 days)
  | ignored (the owner said so).
- goals: measurable targets the Team Lead proposes in a meeting; the owner accepts them.
  metric is one of the metrics code can measure (del_social.team.metrics); baseline and
  current are measured by code, never by a model.
- daily_reports.kind gains 'meeting' (the Team Lead's meeting with the agents).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"


def _protect(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = app_current_tenant_id())
            WITH CHECK (tenant_id = app_current_tenant_id())
    """)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")
    op.execute(f"CREATE TRIGGER fill_tenant_id BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()")


def upgrade() -> None:
    op.create_table(
        "competitors",
        sa.Column("competitor_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("name", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("followers", sa.Integer()),
        sa.Column("last_post_at", sa.DateTime(timezone=True)),
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("source IN ('owner', 'discovered')", name="ck_competitors_source"),
        sa.CheckConstraint("status IN ('active', 'invalid', 'inactive', 'ignored')", name="ck_competitors_status"),
        sa.UniqueConstraint("tenant_id", "username", name="uq_competitors_username"),
    )
    _protect("competitors")

    op.create_table(
        "goals",
        sa.Column("goal_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("metric", sa.Text(), nullable=False),
        sa.Column("baseline", sa.Numeric(14, 2)),
        sa.Column("target", sa.Numeric(14, 2), nullable=False),
        sa.Column("current", sa.Numeric(14, 2)),
        sa.Column("due", sa.Date(), nullable=False),
        sa.Column("why", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="proposed"),
        sa.Column("report_id", sa.Uuid(), sa.ForeignKey("daily_reports.report_id", ondelete="RESTRICT")),
        sa.Column("decided_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('proposed', 'active', 'achieved', 'missed', 'dropped')", name="ck_goals_status"),
    )
    _protect("goals")

    op.drop_constraint("ck_daily_reports_kind", "daily_reports")
    op.create_check_constraint("ck_daily_reports_kind", "daily_reports", "kind IN ('market', 'briefing', 'meeting')")


def downgrade() -> None:
    op.execute("DELETE FROM daily_reports WHERE kind = 'meeting' AND report_id NOT IN (SELECT report_id FROM goals WHERE report_id IS NOT NULL)")
    op.drop_table("goals")
    op.execute("DELETE FROM daily_reports WHERE kind = 'meeting'")
    op.drop_constraint("ck_daily_reports_kind", "daily_reports")
    op.create_check_constraint("ck_daily_reports_kind", "daily_reports", "kind IN ('market', 'briefing')")
    op.drop_table("competitors")
