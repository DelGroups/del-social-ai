"""accounts, memberships, sessions, invitations, password resets

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-26

Replaces the per-tenant `users` table (0 rows in production) with global
`accounts` + per-tenant `memberships`. See docs/decisions/002-auth-accounts-memberships.md.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"
TENANT_PREDICATE = "tenant_id = app_current_tenant_id()"
ACCOUNT_PREDICATE = "account_id = app_current_account_id()"

member_role = postgresql.ENUM(name="member_role", create_type=False)

# Pre-login lookups. SECURITY DEFINER bypasses RLS, so each returns only what
# its one step needs, pins search_path, and is executable by del_app only.
DEFINER_FUNCTIONS = {
    "auth_login_lookup(text)": """
        CREATE FUNCTION auth_login_lookup(p_email text)
        RETURNS TABLE (account_id uuid, password_hash text, is_active boolean)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT a.account_id, a.password_hash, a.is_active
            FROM accounts a
            WHERE a.email = lower(p_email)
        $$
    """,
    "auth_session_account(bytea)": """
        CREATE FUNCTION auth_session_account(p_token_hash bytea)
        RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT s.account_id
            FROM auth_sessions s
            JOIN accounts a ON a.account_id = s.account_id
            WHERE s.token_hash = p_token_hash
              AND s.revoked_at IS NULL
              AND s.expires_at > now()
              AND s.idle_expires_at > now()
              AND a.is_active
        $$
    """,
    "auth_my_memberships()": """
        CREATE FUNCTION auth_my_memberships()
        RETURNS TABLE (tenant_id uuid, tenant_name text, role member_role)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT m.tenant_id, t.name, m.role
            FROM memberships m
            JOIN tenants t ON t.tenant_id = m.tenant_id
            WHERE m.account_id = app_current_account_id()
            ORDER BY t.name
        $$
    """,
    "auth_invitation_by_token(bytea)": """
        CREATE FUNCTION auth_invitation_by_token(p_token_hash bytea)
        RETURNS TABLE (
            invitation_id uuid, tenant_id uuid, tenant_name text, email text, role member_role,
            expires_at timestamptz, accepted_at timestamptz, revoked_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT i.invitation_id, i.tenant_id, t.name, i.email, i.role,
                   i.expires_at, i.accepted_at, i.revoked_at
            FROM invitations i
            JOIN tenants t ON t.tenant_id = i.tenant_id
            WHERE i.token_hash = p_token_hash
        $$
    """,
    "auth_password_reset_by_token(bytea)": """
        CREATE FUNCTION auth_password_reset_by_token(p_token_hash bytea)
        RETURNS uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT r.account_id
            FROM password_resets r
            JOIN accounts a ON a.account_id = r.account_id
            WHERE r.token_hash = p_token_hash
              AND r.used_at IS NULL
              AND r.expires_at > now()
              AND a.is_active
        $$
    """,
}


def _uuid_pk(name: str) -> sa.Column:
    return sa.Column(
        name, sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _ts(name: str, nullable: bool = False, default_now: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.func.now() if default_now else None,
    )


def _fk(name: str, target: str, ondelete: str, nullable: bool = False) -> sa.Column:
    return sa.Column(name, sa.Uuid(), sa.ForeignKey(target, ondelete=ondelete), nullable=nullable)


def _token_hash() -> sa.Column:
    return sa.Column("token_hash", sa.LargeBinary(), nullable=False, unique=True)


def _protect(table: str, predicate: str, policy: str, grants: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY {policy} ON {table} USING ({predicate}) WITH CHECK ({predicate})")
    op.execute(f"GRANT {grants} ON {table} TO {APP_ROLE}")


def _fill_tenant_trigger(table: str) -> None:
    op.execute(f"""
        CREATE TRIGGER fill_tenant_id BEFORE INSERT ON {table}
            FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()
    """)


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION app_current_account_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.account_id', true), '')::uuid
        $$
    """)

    op.drop_table("users")
    op.execute("ALTER TYPE user_role RENAME TO member_role")

    # --- global identity ---
    op.create_table(
        "accounts",
        _uuid_pk("account_id"),
        sa.Column("email", sa.Text(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts("created_at", default_now=True),
        _ts("password_changed_at", default_now=True),
        _ts("last_login_at", nullable=True),
        sa.CheckConstraint("email = lower(email)", name="ck_accounts_email_lowercase"),
    )
    _protect("accounts", ACCOUNT_PREDICATE, "account_isolation", "SELECT, INSERT, UPDATE")

    # --- per-tenant access ---
    op.create_table(
        "memberships",
        _uuid_pk("membership_id"),
        _fk("tenant_id", "tenants.tenant_id", "RESTRICT"),
        _fk("account_id", "accounts.account_id", "RESTRICT"),
        sa.Column("role", member_role, nullable=False, server_default="viewer"),
        _ts("created_at", default_now=True),
        sa.UniqueConstraint("tenant_id", "account_id", name="uq_memberships_tenant_account"),
    )
    op.create_index("ix_memberships_account_id", "memberships", ["account_id"])
    _protect("memberships", TENANT_PREDICATE, "tenant_isolation", "SELECT, INSERT, UPDATE, DELETE")
    _fill_tenant_trigger("memberships")

    op.create_table(
        "invitations",
        _uuid_pk("invitation_id"),
        _fk("tenant_id", "tenants.tenant_id", "RESTRICT"),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", member_role, nullable=False),
        _token_hash(),
        _fk("invited_by", "accounts.account_id", "SET NULL", nullable=True),
        _ts("created_at", default_now=True),
        _ts("expires_at"),
        _ts("accepted_at", nullable=True),
        _fk("accepted_by", "accounts.account_id", "SET NULL", nullable=True),
        _ts("revoked_at", nullable=True),
        sa.CheckConstraint("email = lower(email)", name="ck_invitations_email_lowercase"),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="ck_invitations_token_hash_len"),
    )
    # At most one open invitation per person per tenant
    op.create_index(
        "uq_invitations_pending",
        "invitations",
        ["tenant_id", "email"],
        unique=True,
        postgresql_where=sa.text("accepted_at IS NULL AND revoked_at IS NULL"),
    )
    _protect("invitations", TENANT_PREDICATE, "tenant_isolation", "SELECT, INSERT, UPDATE")
    _fill_tenant_trigger("invitations")

    # --- per-account auth state ---
    op.create_table(
        "auth_sessions",
        _uuid_pk("session_id"),
        _fk("account_id", "accounts.account_id", "CASCADE"),
        _token_hash(),
        _ts("created_at", default_now=True),
        _ts("expires_at"),
        _ts("idle_expires_at"),
        _ts("last_seen_at", default_now=True),
        _ts("revoked_at", nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="ck_auth_sessions_token_hash_len"),
    )
    op.create_index("ix_auth_sessions_account_id", "auth_sessions", ["account_id"])
    _protect("auth_sessions", ACCOUNT_PREDICATE, "account_isolation", "SELECT, INSERT, UPDATE")

    op.create_table(
        "password_resets",
        _uuid_pk("reset_id"),
        _fk("account_id", "accounts.account_id", "CASCADE"),
        _token_hash(),
        _fk("created_by", "accounts.account_id", "SET NULL", nullable=True),
        _ts("created_at", default_now=True),
        _ts("expires_at"),
        _ts("used_at", nullable=True),
        sa.CheckConstraint("octet_length(token_hash) = 32", name="ck_password_resets_token_hash_len"),
    )
    op.create_index("ix_password_resets_account_id", "password_resets", ["account_id"])
    _protect("password_resets", ACCOUNT_PREDICATE, "account_isolation", "SELECT, INSERT, UPDATE")

    for signature, ddl in DEFINER_FUNCTIONS.items():
        op.execute(ddl)
        op.execute(f"REVOKE ALL ON FUNCTION {signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION {signature} TO {APP_ROLE}")


def downgrade() -> None:
    for signature in DEFINER_FUNCTIONS:
        op.execute(f"DROP FUNCTION {signature}")

    for table in ("password_resets", "auth_sessions", "invitations", "memberships", "accounts"):
        op.drop_table(table)

    op.execute("ALTER TYPE member_role RENAME TO user_role")

    # Recreate 0001's users table exactly
    op.create_table(
        "users",
        _uuid_pk("user_id"),
        _fk("tenant_id", "tenants.tenant_id", "RESTRICT"),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "role",
            postgresql.ENUM(name="user_role", create_type=False),
            nullable=False,
            server_default="viewer",
        ),
        _ts("created_at", default_now=True),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
    )
    _protect("users", TENANT_PREDICATE, "tenant_isolation", "SELECT, INSERT, UPDATE, DELETE")
    _fill_tenant_trigger("users")

    op.execute("DROP FUNCTION app_current_account_id()")
