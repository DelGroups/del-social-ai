"""add-ons and credits: YouTube Studio sold on its own or next to a package (ADR 012)

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-28

- addons, credit_packs: the catalog (global, read-only for the app).
- tenant_addons: which add-ons a company has, from when to when. One active row per add-on.
- credit_ledger: every credit movement (monthly spending, bought packs, spending, refunds). A
  balance is always computed from these rows by code (billing/credits.py), never stored.
- purchase_requests: an owner asks for an add-on or a credit pack; the platform admin fulfils it.
- addon_tenants(addon): ids of companies with that add-on active, for background work.
- platform_addon_overview(): add-ons and credit balances per company, platform admins only.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020"
down_revision: str | None = "0019"
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


def _catalog(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY read_catalog ON {table} FOR SELECT USING (true)")
    op.execute(f"GRANT SELECT ON {table} TO {APP_ROLE}")


def upgrade() -> None:
    op.create_table(
        "addons",
        sa.Column("addon_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("price_azn", sa.Numeric(10, 2), nullable=False),
        sa.Column("monthly_credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("features", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    _catalog("addons")
    op.execute("""
        INSERT INTO addons (addon_id, name, price_azn, monthly_credits, features, sort) VALUES
        ('youtube', 'YouTube Studio', 49, 100, '{"channels": 1}', 1)
    """)

    op.create_table(
        "credit_packs",
        sa.Column("pack_id", sa.Text(), primary_key=True),
        sa.Column("addon_id", sa.Text(), sa.ForeignKey("addons.addon_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("credits", sa.Integer(), nullable=False),
        sa.Column("price_azn", sa.Numeric(10, 2), nullable=False),
        sa.Column("sort", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("credits > 0", name="ck_credit_packs_credits"),
    )
    _catalog("credit_packs")
    op.execute("""
        INSERT INTO credit_packs (pack_id, addon_id, credits, price_azn, sort) VALUES
        ('yt_100', 'youtube', 100, 15, 1),
        ('yt_300', 'youtube', 300, 39, 2),
        ('yt_1000', 'youtube', 1000, 110, 3)
    """)

    op.create_table(
        "tenant_addons",
        sa.Column("tenant_addon_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("addon_id", sa.Text(), sa.ForeignKey("addons.addon_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True)),  # NULL = no end date
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('active', 'ended')", name="ck_tenant_addons_status"),
    )
    op.create_index("ux_tenant_addons_one_active", "tenant_addons", ["tenant_id", "addon_id"], unique=True,
                    postgresql_where=sa.text("status = 'active'"))
    _protect("tenant_addons", "SELECT, INSERT, UPDATE")

    op.create_table(
        "credit_ledger",
        sa.Column("entry_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("addon_id", sa.Text(), sa.ForeignKey("addons.addon_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("bucket", sa.Text(), nullable=False),  # monthly | purchased
        sa.Column("delta", sa.Integer(), nullable=False),  # + bought / refunded, − spent
        sa.Column("reason", sa.Text(), nullable=False),  # purchase | grant | spend:<work> | refund
        sa.Column("ref_id", sa.Uuid()),  # the job the credits paid for
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("bucket IN ('monthly', 'purchased')", name="ck_credit_ledger_bucket"),
        sa.CheckConstraint("delta <> 0", name="ck_credit_ledger_delta"),
    )
    op.create_index("ix_credit_ledger_tenant_created", "credit_ledger", ["tenant_id", "addon_id", "created_at"])
    _protect("credit_ledger", "SELECT, INSERT")  # a ledger is never edited

    op.create_table(
        "purchase_requests",
        sa.Column("request_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),  # addon | credits
        sa.Column("item_id", sa.Text(), nullable=False),  # addon_id or pack_id
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('addon', 'credits')", name="ck_purchase_requests_kind"),
        sa.CheckConstraint("status IN ('open', 'done')", name="ck_purchase_requests_status"),
    )
    _protect("purchase_requests", "SELECT, INSERT, UPDATE")

    op.execute("""
        CREATE FUNCTION addon_tenants(addon text)
        RETURNS TABLE (tenant_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT a.tenant_id FROM tenant_addons a
            WHERE a.addon_id = addon AND a.status = 'active' AND (a.expires_at IS NULL OR a.expires_at > now())
            ORDER BY a.tenant_id
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION addon_tenants(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION addon_tenants(text) TO {APP_ROLE}")

    # Add-ons and credit balances per company, for platform admins only (billing numbers, no content)
    op.execute("""
        CREATE FUNCTION platform_addon_overview()
        RETURNS TABLE (
            tenant_id uuid, addon_id text, status text, starts_at timestamptz, expires_at timestamptz,
            purchased_balance bigint, monthly_spent bigint, open_requests bigint
        )
        LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM accounts a WHERE a.account_id = app_current_account_id() AND a.is_platform_admin) THEN
                RAISE EXCEPTION 'platform admins only' USING ERRCODE = '42501';
            END IF;
            RETURN QUERY
            SELECT ta.tenant_id, ta.addon_id, ta.status, ta.starts_at, ta.expires_at,
                   COALESCE((SELECT sum(l.delta) FROM credit_ledger l WHERE l.tenant_id = ta.tenant_id
                        AND l.addon_id = ta.addon_id AND l.bucket = 'purchased'), 0)::bigint,
                   COALESCE((SELECT -sum(l.delta) FROM credit_ledger l, subscription_period(ta.starts_at) w
                        WHERE l.tenant_id = ta.tenant_id AND l.addon_id = ta.addon_id AND l.bucket = 'monthly'
                        AND l.created_at >= w.period_start AND l.created_at < w.period_end), 0)::bigint,
                   (SELECT count(*) FROM purchase_requests r WHERE r.tenant_id = ta.tenant_id AND r.status = 'open')
            FROM tenant_addons ta
            WHERE ta.status = 'active'
            ORDER BY ta.tenant_id, ta.addon_id;
        END
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION platform_addon_overview() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION platform_addon_overview() TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION platform_addon_overview()")
    op.execute("DROP FUNCTION addon_tenants(text)")
    op.drop_table("purchase_requests")
    op.drop_table("credit_ledger")
    op.drop_table("tenant_addons")
    op.drop_table("credit_packs")
    op.drop_table("addons")
