"""plans and subscriptions: what each company bought, and its monthly allowance (ADR 007)

Revision ID: 0015
Revises: 0014
Create Date: 2026-09-27

- plans: the catalog (Basic / Pro / Enterprise from the commercial proposal). Global, read-only
  for the app; NULL limit = unlimited.
- subscriptions: a company's plan, when it started and when it expires. One active per company.
  The monthly allowance window runs from the start date (subscription_period()).
- plan_requests: an owner asks for an upgrade; the platform admin assigns the plan.
- platform_tenant_overview(): plan, usage and AI cost per company, for platform admins only
  (billing aggregates; no content). Checked inside the function, not only in the route.
Existing companies get Enterprise without expiry (Del Furniture is our own company).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"


def _protect(table: str, grants: str) -> None:
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
        "plans",
        sa.Column("plan_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("price_azn", sa.Numeric(10, 2), nullable=False),
        sa.Column("posts_per_month", sa.Integer()),  # published posts; NULL = unlimited
        sa.Column("draft_factor", sa.Integer(), nullable=False, server_default="3"),  # drafts allowed = factor × posts
        sa.Column("channels", sa.Integer()),
        sa.Column("users", sa.Integer()),
        sa.Column("video_credits", sa.Integer()),  # per month
        sa.Column("features", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    # A global catalog: everyone may read it, nobody but the owner role may change it
    op.execute("ALTER TABLE plans ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE plans FORCE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY read_catalog ON plans FOR SELECT USING (true)")
    op.execute(f"GRANT SELECT ON plans TO {APP_ROLE}")
    op.execute("""
        INSERT INTO plans (plan_id, name, price_azn, posts_per_month, channels, users, video_credits, features, sort) VALUES
        ('basic', 'Basic', 290, 30, 2, 1, 5,
         '{"auto_support": false, "sales_agent": false, "weekly_report": false, "erp": false}', 1),
        ('pro', 'Pro', 690, 90, 4, 5, 15,
         '{"auto_support": true, "sales_agent": true, "weekly_report": true, "erp": false}', 2),
        ('enterprise', 'Enterprise', 1500, NULL, NULL, NULL, 30,
         '{"auto_support": true, "sales_agent": true, "weekly_report": true, "erp": true}', 3)
    """)

    op.create_table(
        "subscriptions",
        sa.Column("subscription_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_id", sa.Text(), sa.ForeignKey("plans.plan_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),  # NULL = no end date
        sa.Column("extra_video_credits", sa.Integer(), nullable=False, server_default="0"),  # bought packs
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'ended')", name="ck_subscriptions_status"),
        sa.CheckConstraint("extra_video_credits >= 0", name="ck_subscriptions_extra_video"),
    )
    op.create_index("ux_subscriptions_one_active", "subscriptions", ["tenant_id"], unique=True,
                    postgresql_where=sa.text("status = 'active'"))
    _protect("subscriptions", "SELECT, INSERT, UPDATE")

    op.create_table(
        "plan_requests",
        sa.Column("request_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("plan_id", sa.Text(), sa.ForeignKey("plans.plan_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('open', 'done')", name="ck_plan_requests_status"),
    )
    _protect("plan_requests", "SELECT, INSERT, UPDATE")

    # The monthly window that contains now, counted from the start date (same rule everywhere)
    op.execute("""
        CREATE FUNCTION subscription_period(starts timestamptz, at timestamptz DEFAULT now())
        RETURNS TABLE (period_start timestamptz, period_end timestamptz)
        LANGUAGE sql STABLE AS $$
            WITH m AS (
                SELECT GREATEST(0, (extract(year FROM age(at, starts)) * 12 + extract(month FROM age(at, starts)))::int) AS n
            )
            SELECT starts + make_interval(months => m.n), starts + make_interval(months => m.n + 1) FROM m
        $$
    """)
    op.execute(f"GRANT EXECUTE ON FUNCTION subscription_period(timestamptz, timestamptz) TO {APP_ROLE}")

    # Billing overview for platform admins: plan, window usage and AI cost per company. No content.
    op.execute("""
        CREATE FUNCTION platform_tenant_overview()
        RETURNS TABLE (
            tenant_id uuid, name text, created_at timestamptz,
            plan_id text, starts_at timestamptz, expires_at timestamptz, extra_video_credits int,
            period_start timestamptz, period_end timestamptz,
            posts_published bigint, posts_scheduled bigint, members bigint, channels bigint,
            ai_cost_month_usd numeric, open_request_plan text, open_request_at timestamptz
        )
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM accounts a WHERE a.account_id = app_current_account_id() AND a.is_platform_admin) THEN
                RAISE EXCEPTION 'platform admins only' USING ERRCODE = '42501';
            END IF;
            RETURN QUERY
            SELECT t.tenant_id, t.name, t.created_at,
                   s.plan_id, s.starts_at, s.expires_at, s.extra_video_credits,
                   w.period_start, w.period_end,
                   (SELECT count(*) FROM posts p WHERE p.tenant_id = t.tenant_id
                        AND p.status IN ('published', 'partly_published')
                        AND p.published_at >= w.period_start AND p.published_at < w.period_end),
                   (SELECT count(*) FROM posts p WHERE p.tenant_id = t.tenant_id AND p.status = 'scheduled'),
                   (SELECT count(*) FROM memberships m WHERE m.tenant_id = t.tenant_id),
                   (SELECT count(*) FROM connections c WHERE c.tenant_id = t.tenant_id),
                   COALESCE((SELECT sum(l.cost_usd) FROM llm_calls l WHERE l.tenant_id = t.tenant_id
                        AND l.created_at >= date_trunc('month', now())), 0)
                   + COALESCE((SELECT sum((ma.edit ->> 'cost_usd')::numeric) FROM media_assets ma
                        WHERE ma.tenant_id = t.tenant_id AND ma.parent_asset_id IS NOT NULL
                        AND ma.created_at >= date_trunc('month', now())), 0),
                   r.plan_id, r.created_at
            FROM tenants t
            LEFT JOIN subscriptions s ON s.tenant_id = t.tenant_id AND s.status = 'active'
            LEFT JOIN LATERAL subscription_period(COALESCE(s.starts_at, t.created_at)) w ON true
            LEFT JOIN LATERAL (
                SELECT pr.plan_id, pr.created_at FROM plan_requests pr
                WHERE pr.tenant_id = t.tenant_id AND pr.status = 'open'
                ORDER BY pr.created_at DESC LIMIT 1
            ) r ON true
            ORDER BY t.created_at;
        END
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION platform_tenant_overview() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION platform_tenant_overview() TO {APP_ROLE}")

    # Companies that exist today keep working without limits
    op.execute("""
        INSERT INTO subscriptions (tenant_id, plan_id, starts_at, expires_at, note)
        SELECT tenant_id, 'enterprise', now(), NULL, 'Assigned when plans were introduced' FROM tenants
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION platform_tenant_overview()")
    op.execute("DROP FUNCTION subscription_period(timestamptz, timestamptz)")
    op.drop_table("plan_requests")
    op.drop_table("subscriptions")
    op.drop_table("plans")
