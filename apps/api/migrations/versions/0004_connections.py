"""connections: connected channel accounts with vault-encrypted tokens

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-26

See docs/decisions/003-connections-token-vault.md. Tenant-scoped with forced RLS
(ADR 001); tenant_id is filled from app.tenant_id when omitted.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"
CHANNELS = ("instagram", "facebook", "telegram", "whatsapp", "tiktok", "youtube")
STATUSES = ("active", "error")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "connections",
        sa.Column("connection_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("token_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("token_expires_at", sa.DateTime(timezone=True)),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column(
            "connected_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "channel", "external_id", name="uq_connections_tenant_channel_external"),
        sa.CheckConstraint(_in("channel", CHANNELS), name="ck_connections_channel"),
        sa.CheckConstraint(_in("status", STATUSES), name="ck_connections_status"),
    )
    op.execute("ALTER TABLE connections ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE connections FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON connections
            USING (tenant_id = app_current_tenant_id())
            WITH CHECK (tenant_id = app_current_tenant_id())
    """)
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON connections TO {APP_ROLE}")
    op.execute("""
        CREATE TRIGGER fill_tenant_id BEFORE INSERT ON connections
            FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()
    """)


def downgrade() -> None:
    op.drop_table("connections")
