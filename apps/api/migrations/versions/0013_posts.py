"""posts: a post from draft to published (photos, caption options, approval, per-channel result)

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-27

docs/phase-1-plan.md steps 5–7 (composer first; the weekly plan fills the same table later).
Tenant-scoped with forced RLS (ADR 001); del_app has no DELETE (posts are archived).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"
STATUSES = ("generating", "ready", "failed", "approved", "publishing", "published", "partly_published", "archived")


def upgrade() -> None:
    op.create_table(
        "posts",
        sa.Column("post_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="generating"),
        sa.Column("product_id", sa.Uuid(), sa.ForeignKey("products.product_id", ondelete="RESTRICT")),
        sa.Column("asset_ids", postgresql.ARRAY(sa.Uuid()), nullable=False),
        sa.Column("format", sa.Text(), nullable=False, server_default="feed"),
        sa.Column("with_logo", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("channels", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("brief", postgresql.JSONB()),
        sa.Column("generation", postgresql.JSONB()),  # pipeline result: options, verdicts, cost
        sa.Column("chosen_option", sa.Integer()),
        sa.Column("caption", sa.Text()),  # the exact text that is published
        sa.Column("error", sa.Text()),
        sa.Column("results", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("approved_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(f"status IN ({', '.join(repr(s) for s in STATUSES)})", name="ck_posts_status"),
        sa.CheckConstraint("format IN ('feed', 'square', 'landscape')", name="ck_posts_format"),
        sa.CheckConstraint("cardinality(asset_ids) BETWEEN 1 AND 10", name="ck_posts_photo_count"),
    )
    op.create_index("ix_posts_tenant_created", "posts", ["tenant_id", "created_at"])
    op.execute("ALTER TABLE posts ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE posts FORCE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON posts
            USING (tenant_id = app_current_tenant_id())
            WITH CHECK (tenant_id = app_current_tenant_id())
    """)
    op.execute(f"GRANT SELECT, INSERT, UPDATE ON posts TO {APP_ROLE}")
    op.execute("""
        CREATE TRIGGER fill_tenant_id BEFORE INSERT ON posts
            FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()
    """)


def downgrade() -> None:
    op.drop_table("posts")
