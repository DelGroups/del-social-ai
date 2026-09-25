"""tenants, users, tenant_secrets with row-level security

Revision ID: 0001
Revises:
Create Date: 2026-09-25

See docs/decisions/001-multi-tenant-rls.md.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"
TENANT_TABLES = ("tenants", "users", "tenant_secrets")
# Tables whose tenant_id is filled from app.tenant_id when omitted on INSERT
CHILD_TABLES = ("users", "tenant_secrets")

user_role = postgresql.ENUM(
    "owner", "admin", "approver", "viewer", name="user_role", create_type=False
)


def _id(name: str) -> sa.Column:
    return sa.Column(
        name, sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def _tenant_fk() -> sa.Column:
    return sa.Column(
        "tenant_id",
        sa.Uuid(),
        sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"),
        nullable=False,
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
    )


def upgrade() -> None:
    # Runtime role for the app: not superuser, no BYPASSRLS, so policies always apply.
    # Created NOLOGIN; enabling login with a password is a separate, deliberate ops step.
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS;
            END IF;
        END $$;
    """)
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")

    # Current tenant from the transaction-local setting. Unset/empty → NULL → no rows (fail closed).
    op.execute("""
        CREATE FUNCTION app_current_tenant_id() RETURNS uuid
        LANGUAGE sql STABLE AS $$
            SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
        $$;
    """)
    op.execute("""
        CREATE FUNCTION app_fill_tenant_id() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.tenant_id IS NULL THEN
                NEW.tenant_id := app_current_tenant_id();
            END IF;
            RETURN NEW;
        END $$;
    """)

    op.execute("CREATE TYPE user_role AS ENUM ('owner', 'admin', 'approver', 'viewer')")

    op.create_table(
        "tenants",
        _id("tenant_id"),
        sa.Column("name", sa.Text(), nullable=False),
        _created_at(),
    )
    op.create_table(
        "users",
        _id("user_id"),
        _tenant_fk(),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("role", user_role, nullable=False, server_default="viewer"),
        _created_at(),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
        sa.CheckConstraint("email = lower(email)", name="ck_users_email_lowercase"),
    )
    op.create_table(
        "tenant_secrets",
        _id("id"),
        _tenant_fk(),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_secrets_tenant_key"),
    )

    for table in TENANT_TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE: the table owner is bound by the policy too (superusers still bypass).
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
                USING (tenant_id = app_current_tenant_id())
                WITH CHECK (tenant_id = app_current_tenant_id())
        """)
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")

    for table in CHILD_TABLES:
        op.execute(f"""
            CREATE TRIGGER fill_tenant_id BEFORE INSERT ON {table}
                FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()
        """)


def downgrade() -> None:
    op.drop_table("tenant_secrets")
    op.drop_table("users")
    op.drop_table("tenants")
    op.execute("DROP TYPE user_role")
    op.execute("DROP FUNCTION app_fill_tenant_id()")
    op.execute("DROP FUNCTION app_current_tenant_id()")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")
    # The role is cluster-wide and may be used by other databases, so it is kept.
