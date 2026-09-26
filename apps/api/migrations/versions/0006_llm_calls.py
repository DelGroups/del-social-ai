"""llm_calls: per-tenant record of every LLM request (tokens, cost, latency)

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-26

CLAUDE.md principle 9. Tenant-scoped with forced RLS (ADR 001). del_app gets SELECT
and INSERT only: usage history can't be edited.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"


def upgrade() -> None:
    op.create_table(
        "llm_calls",
        sa.Column("call_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("prompt_ref", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6)),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("trace_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('ok', 'error')", name="ck_llm_calls_status"),
    )
    op.create_index("ix_llm_calls_tenant_created", "llm_calls", ["tenant_id", "created_at"])
    op.execute("ALTER TABLE llm_calls ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE llm_calls FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON llm_calls
            USING (tenant_id = app_current_tenant_id())
            WITH CHECK (tenant_id = app_current_tenant_id())
    """)
    op.execute(f"GRANT SELECT, INSERT ON llm_calls TO {APP_ROLE}")
    op.execute("""
        CREATE TRIGGER fill_tenant_id BEFORE INSERT ON llm_calls
            FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()
    """)


def downgrade() -> None:
    op.drop_table("llm_calls")
