"""eval_runs, eval_items: agent eval runs and human ratings

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-26

docs/phase-1-plan.md §10. Tenant-scoped with forced RLS (ADR 001). No DELETE for del_app.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"
TABLES = ("eval_runs", "eval_items")


def _tenant() -> sa.Column:
    return sa.Column(
        "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False
    )


def _created() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("run_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant(),
        sa.Column("suite", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("prompt_refs", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("brand_version", sa.Integer(), nullable=False),
        sa.Column("briefs_total", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        _created(),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('running', 'done', 'failed')", name="ck_eval_runs_status"),
    )
    op.create_table(
        "eval_items",
        sa.Column("item_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("eval_runs.run_id", ondelete="RESTRICT"), nullable=False),
        _tenant(),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("brief", postgresql.JSONB(), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("error", sa.Text()),
        sa.Column("ratings", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("note", sa.Text()),
        sa.Column("rated_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("rated_at", sa.DateTime(timezone=True)),
        _created(),
    )
    op.create_index("ix_eval_items_run_id", "eval_items", ["run_id"])
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = app_current_tenant_id())
                WITH CHECK (tenant_id = app_current_tenant_id())
        """)
        op.execute(f"GRANT SELECT, INSERT, UPDATE ON {table} TO {APP_ROLE}")
        op.execute(f"""
            CREATE TRIGGER fill_tenant_id BEFORE INSERT ON {table}
                FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()
        """)


def downgrade() -> None:
    op.drop_table("eval_items")
    op.drop_table("eval_runs")
