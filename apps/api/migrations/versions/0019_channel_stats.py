"""channel_stats: one snapshot per connected channel per day, for the channel cards on the home page

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-28

- channel_stats: followers, posts, views, likes, comments (+ channel-specific extras) of one
  connection on one Baku day. Collected by code once a day (connections/stats.py); growth is
  computed from these rows, never estimated.
- stats_tenants(): ids of companies with at least one connection, for the daily collection
  (SECURITY DEFINER, ids only; ADR 001/002).
- Backfill: the Instagram numbers the morning research already collected (daily_reports.input.own),
  so the cards show a history from the first day.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"


def upgrade() -> None:
    op.create_table(
        "channel_stats",
        sa.Column("stat_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("connection_id", sa.Uuid(), sa.ForeignKey("connections.connection_id", ondelete="CASCADE"), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("followers", sa.BigInteger()),  # followers / page followers / subscribers
        sa.Column("posts", sa.BigInteger()),  # posts / videos
        sa.Column("views", sa.BigInteger()),  # total channel views (YouTube)
        sa.Column("likes", sa.BigInteger()),  # on the recent posts counted in extra.recent
        sa.Column("comments", sa.BigInteger()),
        sa.Column("extra", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("collected_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("connection_id", "day", name="uq_channel_stats_connection_day"),
    )
    op.create_index("ix_channel_stats_tenant_day", "channel_stats", ["tenant_id", "day"])
    op.execute("ALTER TABLE channel_stats ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE channel_stats FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON channel_stats
            USING (tenant_id = app_current_tenant_id())
            WITH CHECK (tenant_id = app_current_tenant_id())
    """)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON channel_stats TO {APP_ROLE}")
    op.execute("CREATE TRIGGER fill_tenant_id BEFORE INSERT ON channel_stats FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()")

    op.execute("""
        CREATE FUNCTION stats_tenants()
        RETURNS TABLE (tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT DISTINCT c.tenant_id FROM connections c ORDER BY c.tenant_id
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION stats_tenants() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION stats_tenants() TO {APP_ROLE}")

    # History from the morning research (Instagram only; one Instagram account per company so far)
    op.execute("""
        INSERT INTO channel_stats (tenant_id, connection_id, day, followers, posts, extra, collected_at)
        SELECT d.tenant_id, c.connection_id, d.day,
               (d.input -> 'own' ->> 'followers')::bigint,
               (d.input -> 'own' ->> 'total_posts')::bigint,
               jsonb_strip_nulls(jsonb_build_object(
                   'username', d.input -> 'own' ->> 'username',
                   'avg_likes', d.input -> 'own' -> 'stats' -> 'avg_likes',
                   'avg_comments', d.input -> 'own' -> 'stats' -> 'avg_comments',
                   'engagement_rate', d.input -> 'own' -> 'stats' -> 'engagement_rate_percent',
                   'source', 'research')),
               COALESCE(d.finished_at, d.created_at)
        FROM daily_reports d
        JOIN LATERAL (
            SELECT connection_id FROM connections
            WHERE tenant_id = d.tenant_id AND channel = 'instagram' ORDER BY created_at LIMIT 1
        ) c ON true
        WHERE d.kind = 'market' AND jsonb_typeof(d.input -> 'own' -> 'followers') = 'number'
        ON CONFLICT (connection_id, day) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION stats_tenants()")
    op.drop_table("channel_stats")
