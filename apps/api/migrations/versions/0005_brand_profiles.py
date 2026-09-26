"""brand_profiles: versioned, append-only brand profile per tenant

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-26

See docs/phase-1-plan.md §2. Tenant-scoped with forced RLS (ADR 001). del_app gets
SELECT and INSERT only: saving creates a new version, old versions are never changed.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"


def upgrade() -> None:
    op.create_table(
        "brand_profiles",
        sa.Column("profile_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("data", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "version", name="uq_brand_profiles_tenant_version"),
        sa.CheckConstraint("version >= 1", name="ck_brand_profiles_version_positive"),
    )
    op.execute("ALTER TABLE brand_profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE brand_profiles FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON brand_profiles
            USING (tenant_id = app_current_tenant_id())
            WITH CHECK (tenant_id = app_current_tenant_id())
    """)
    op.execute(f"GRANT SELECT, INSERT ON brand_profiles TO {APP_ROLE}")
    op.execute("""
        CREATE TRIGGER fill_tenant_id BEFORE INSERT ON brand_profiles
            FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()
    """)


def downgrade() -> None:
    op.drop_table("brand_profiles")
