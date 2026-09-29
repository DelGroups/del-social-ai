"""yt_chat: the owner's conversation with the YouTube team's manager (ADR 012, revision)

Revision ID: 0023
Revises: 0022
Create Date: 2026-09-29

One row per message: the owner (role user) or a team member (role agent, agent = yt_lead,
yt_reviewer, …). payload holds a card: which report, video or design the message is about, so the
panel can link to it. Per company (RLS), apart from the social team's chat.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"


def upgrade() -> None:
    op.create_table(
        "yt_chat",
        sa.Column("message_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("agent", sa.Text()),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB()),
        sa.Column("author", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("role IN ('user', 'agent')", name="ck_yt_chat_role"),
    )
    op.create_index("ix_yt_chat_tenant_created", "yt_chat", ["tenant_id", "created_at"])
    op.execute("ALTER TABLE yt_chat ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE yt_chat FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON yt_chat
            USING (tenant_id = app_current_tenant_id())
            WITH CHECK (tenant_id = app_current_tenant_id())
    """)
    op.execute(f"GRANT SELECT, INSERT ON yt_chat TO {APP_ROLE}")
    op.execute("CREATE TRIGGER fill_tenant_id BEFORE INSERT ON yt_chat FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()")


def downgrade() -> None:
    op.drop_table("yt_chat")
