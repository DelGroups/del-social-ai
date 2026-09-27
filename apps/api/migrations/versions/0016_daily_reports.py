"""daily work: market research and the Team Lead's morning report (ADR 008)

Revision ID: 0016
Revises: 0015
Create Date: 2026-09-27

- daily_reports: one row per company, kind (market | briefing) and Baku day. The row is
  claimed before the work starts (unique key), so a report is never made twice by accident.
  input = what code collected, output = the agent's report, sources = web pages used.
- chat_messages.payload: structured cards in the Team Room (a report, suggestions the owner
  can accept). del_app may update only this column (to mark a suggestion as done).
- daily_tenants(): ids of companies with an active package, for the morning loop
  (SECURITY DEFINER, returns ids only; ADR 001/002).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"


def upgrade() -> None:
    op.create_table(
        "daily_reports",
        sa.Column("report_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),  # Baku date
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("input", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("output", postgresql.JSONB()),
        sa.Column("sources", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("cost_usd", sa.Numeric(12, 6)),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('market', 'briefing')", name="ck_daily_reports_kind"),
        sa.CheckConstraint("status IN ('running', 'done', 'failed')", name="ck_daily_reports_status"),
        sa.UniqueConstraint("tenant_id", "kind", "day", name="uq_daily_reports_day"),
    )
    op.execute("ALTER TABLE daily_reports ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE daily_reports FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON daily_reports
            USING (tenant_id = app_current_tenant_id())
            WITH CHECK (tenant_id = app_current_tenant_id())
    """)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON daily_reports TO {APP_ROLE}")
    op.execute("CREATE TRIGGER fill_tenant_id BEFORE INSERT ON daily_reports FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()")

    op.add_column("chat_messages", sa.Column("payload", postgresql.JSONB()))
    op.execute(f"GRANT UPDATE (payload) ON chat_messages TO {APP_ROLE}")

    op.execute("""
        CREATE FUNCTION daily_tenants()
        RETURNS TABLE (tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT s.tenant_id FROM subscriptions s
            WHERE s.status = 'active' AND (s.expires_at IS NULL OR s.expires_at > now())
            ORDER BY s.tenant_id
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION daily_tenants() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION daily_tenants() TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION daily_tenants()")
    op.execute(f"REVOKE UPDATE (payload) ON chat_messages FROM {APP_ROLE}")
    op.drop_column("chat_messages", "payload")
    op.drop_table("daily_reports")
