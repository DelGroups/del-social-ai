"""team room: chat with the Team Lead, tasks (wizard steps), live agent events, scheduled posts

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-27

- chat_messages: the conversation with the Team Lead (and agents answering in it)
- tasks: one instruction turned into steps the agents walk through, pausing for approval
- agent_events: what each agent is doing, for the live panel and the activity feed
- posts.scheduled_at + status 'scheduled'; due_scheduled_posts() lets the scheduler find
  due posts across tenants without seeing anything else (SECURITY DEFINER, ADR 001/002)
All tenant-scoped with forced RLS; del_app has no DELETE.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"
OLD_STATUSES = ("generating", "ready", "failed", "approved", "publishing", "published", "partly_published", "archived")
NEW_STATUSES = OLD_STATUSES + ("scheduled",)


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False)


def _created() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _protect(table: str, grants: str = "SELECT, INSERT, UPDATE") -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = app_current_tenant_id())
            WITH CHECK (tenant_id = app_current_tenant_id())
    """)
    op.execute(f"GRANT {grants} ON {table} TO {APP_ROLE}")
    op.execute(f"CREATE TRIGGER fill_tenant_id BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()")


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),  # post | analyze
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("steps", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("post_id", sa.Uuid(), sa.ForeignKey("posts.post_id", ondelete="RESTRICT")),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        _created(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('running', 'waiting_approval', 'scheduled', 'done', 'failed', 'cancelled')", name="ck_tasks_status"
        ),
    )
    op.create_index("ix_tasks_tenant_created", "tasks", ["tenant_id", "created_at"])
    _protect("tasks")

    op.create_table(
        "chat_messages",
        sa.Column("message_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant(),
        sa.Column("role", sa.Text(), nullable=False),  # user | agent
        sa.Column("agent", sa.Text()),  # team_lead, copywriter, … (role=agent)
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.task_id", ondelete="RESTRICT")),
        sa.Column("post_id", sa.Uuid(), sa.ForeignKey("posts.post_id", ondelete="RESTRICT")),  # approval card
        sa.Column("author", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        _created(),
        sa.CheckConstraint("role IN ('user', 'agent')", name="ck_chat_messages_role"),
    )
    op.create_index("ix_chat_messages_tenant_created", "chat_messages", ["tenant_id", "created_at"])
    _protect("chat_messages", "SELECT, INSERT")

    op.create_table(
        "agent_events",
        sa.Column("event_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant(),
        sa.Column("agent", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),  # started | finished | failed | info
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("task_id", sa.Uuid(), sa.ForeignKey("tasks.task_id", ondelete="RESTRICT")),
        sa.Column("post_id", sa.Uuid(), sa.ForeignKey("posts.post_id", ondelete="RESTRICT")),
        _created(),
        sa.CheckConstraint("kind IN ('started', 'finished', 'failed', 'info')", name="ck_agent_events_kind"),
    )
    op.create_index("ix_agent_events_tenant_created", "agent_events", ["tenant_id", "created_at"])
    _protect("agent_events", "SELECT, INSERT")

    op.add_column("posts", sa.Column("scheduled_at", sa.DateTime(timezone=True)))
    op.add_column("posts", sa.Column("task_id", sa.Uuid()))  # no FK: tasks reference posts
    op.drop_constraint("ck_posts_status", "posts")
    op.create_check_constraint("ck_posts_status", "posts", f"status IN ({', '.join(repr(s) for s in NEW_STATUSES)})")

    # The scheduler finds due posts of every tenant, and nothing else
    op.execute("""
        CREATE FUNCTION due_scheduled_posts()
        RETURNS TABLE (tenant_id uuid, post_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT p.tenant_id, p.post_id FROM posts p
            WHERE p.status = 'scheduled' AND p.scheduled_at <= now()
            ORDER BY p.scheduled_at
            LIMIT 50
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION due_scheduled_posts() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION due_scheduled_posts() TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION due_scheduled_posts()")
    op.drop_constraint("ck_posts_status", "posts")
    op.create_check_constraint("ck_posts_status", "posts", f"status IN ({', '.join(repr(s) for s in OLD_STATUSES)})")
    op.drop_column("posts", "task_id")
    op.drop_column("posts", "scheduled_at")
    op.drop_table("agent_events")
    op.drop_table("chat_messages")
    op.drop_table("tasks")
