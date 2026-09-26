"""member emails for tenant managers; column-level grants on accounts

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-26

- auth_tenant_members(): the member list (with emails) of the current tenant only.
  accounts RLS hides other people's rows, but owners/admins need their members' emails.
- del_app may insert only (account_id, email, password_hash) and update only password
  and login timestamps. It can never set is_platform_admin or is_active, even on its own
  row; platform admins are created with the owner's credentials (del_social.cli).
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"
INSERT_COLUMNS = "account_id, email, password_hash"
UPDATE_COLUMNS = "password_hash, password_changed_at, last_login_at"


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION auth_tenant_members()
        RETURNS TABLE (
            membership_id uuid, account_id uuid, email text, role member_role, created_at timestamptz
        )
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT m.membership_id, m.account_id, a.email, m.role, m.created_at
            FROM memberships m
            JOIN accounts a ON a.account_id = m.account_id
            WHERE m.tenant_id = app_current_tenant_id()
            ORDER BY m.created_at, a.email
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION auth_tenant_members() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION auth_tenant_members() TO {APP_ROLE}")

    op.execute(f"REVOKE INSERT, UPDATE ON accounts FROM {APP_ROLE}")
    op.execute(f"GRANT INSERT ({INSERT_COLUMNS}) ON accounts TO {APP_ROLE}")
    op.execute(f"GRANT UPDATE ({UPDATE_COLUMNS}) ON accounts TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT ({INSERT_COLUMNS}), UPDATE ({UPDATE_COLUMNS}) ON accounts FROM {APP_ROLE}")
    op.execute(f"GRANT INSERT, UPDATE ON accounts TO {APP_ROLE}")
    op.execute("DROP FUNCTION auth_tenant_members()")
