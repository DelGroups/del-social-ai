"""YouTube Studio: videos, reports, ideas, publishing kits, thumbnails, comment replies (ADR 012)

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-28

Every table is per company (tenant_id + RLS) and per connected channel (connection_id, deleted with
the connection). Numbers are copied from YouTube or computed by code; model output is kept apart
(output columns) from the facts it was given (input columns).
- yt_settings: the owner's choices per channel (report rhythm, languages, what the channel is about).
- yt_videos: the channel's videos as YouTube last reported them.
- yt_video_snapshots: view/like/comment counts over time, for "last hours" numbers.
- yt_reports: pulse | daily | review | ideas, with the numbers given (input) and the text (output).
- yt_competitors: channels the owner or the team watches.
- yt_ideas: video ideas from the ideas research, with what the owner did with them.
- yt_drafts: a publishing kit for one video (titles, description, tags, chapters, translations).
- yt_thumbnails: a designed thumbnail (the design as data; the image is rendered by code).
- yt_replies: reply drafts for comments, sent only after the owner approves.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "del_app"
JSON = postgresql.JSONB()
EMPTY = sa.text("'{}'::jsonb")


def _protect(table: str, grants: str = "SELECT, INSERT, UPDATE, DELETE") -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(f"""
        CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = app_current_tenant_id())
            WITH CHECK (tenant_id = app_current_tenant_id())
    """)
    op.execute(f"GRANT {grants} ON {table} TO {APP_ROLE}")
    op.execute(f"CREATE TRIGGER fill_tenant_id BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION app_fill_tenant_id()")


def _base(name: str, *cols: sa.Column, key: str | None = None) -> None:
    op.create_table(
        name,
        *( [sa.Column(key, sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()"))] if key else [] ),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("connection_id", sa.Uuid(), sa.ForeignKey("connections.connection_id", ondelete="CASCADE"), nullable=False),
        *cols,
    )


def _now(name: str = "created_at") -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def upgrade() -> None:
    op.create_table(
        "yt_settings",
        sa.Column("connection_id", sa.Uuid(), sa.ForeignKey("connections.connection_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("data", JSON, nullable=False, server_default=EMPTY),
        _now("updated_at"),
    )
    _protect("yt_settings", "SELECT, INSERT, UPDATE")

    _base(
        "yt_videos",
        sa.Column("video_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("category_id", sa.Text()),
        sa.Column("language", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("duration_s", sa.Integer()),
        sa.Column("privacy", sa.Text()),  # public | unlisted | private
        sa.Column("publish_at", sa.DateTime(timezone=True)),  # scheduled on YouTube
        sa.Column("is_short", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("thumbnail_url", sa.Text()),
        sa.Column("views", sa.BigInteger()),
        sa.Column("likes", sa.BigInteger()),
        sa.Column("comments", sa.BigInteger()),
        sa.Column("has_captions", sa.Boolean(), nullable=False, server_default=sa.false()),
        _now("synced_at"),
        sa.PrimaryKeyConstraint("connection_id", "video_id", name="pk_yt_videos"),
    )
    op.create_index("ix_yt_videos_tenant_published", "yt_videos", ["tenant_id", "published_at"])
    _protect("yt_videos", "SELECT, INSERT, UPDATE, DELETE")

    _base(
        "yt_video_snapshots",
        sa.Column("video_id", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("views", sa.BigInteger()),
        sa.Column("likes", sa.BigInteger()),
        sa.Column("comments", sa.BigInteger()),
        sa.PrimaryKeyConstraint("connection_id", "video_id", "at", name="pk_yt_video_snapshots"),
    )
    _protect("yt_video_snapshots", "SELECT, INSERT, DELETE")

    _base(
        "yt_reports",
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),
        sa.Column("period_start", sa.DateTime(timezone=True)),
        sa.Column("period_end", sa.DateTime(timezone=True)),
        sa.Column("input", JSON, nullable=False, server_default=EMPTY),
        sa.Column("output", JSON),
        sa.Column("sources", JSON, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Numeric(12, 6)),
        sa.Column("error", sa.Text()),
        sa.Column("requested_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        _now(),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('pulse', 'daily', 'review', 'ideas')", name="ck_yt_reports_kind"),
        sa.CheckConstraint("status IN ('running', 'done', 'failed')", name="ck_yt_reports_status"),
        key="report_id",
    )
    op.create_index("ix_yt_reports_tenant_created", "yt_reports", ["tenant_id", "kind", "created_at"])
    _protect("yt_reports", "SELECT, INSERT, UPDATE")

    _base(
        "yt_competitors",
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("handle", sa.Text()),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("subscribers", sa.BigInteger()),
        sa.Column("videos", sa.BigInteger()),
        sa.Column("views", sa.BigInteger()),
        sa.Column("avatar", sa.Text()),
        sa.Column("source", sa.Text(), nullable=False, server_default="owner"),  # owner | discovered
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),  # active | ignored
        sa.Column("checked_at", sa.DateTime(timezone=True)),
        _now(),
        sa.UniqueConstraint("connection_id", "channel_id", name="uq_yt_competitors_channel"),
        key="competitor_id",
    )
    _protect("yt_competitors")

    _base(
        "yt_ideas",
        sa.Column("report_id", sa.Uuid(), sa.ForeignKey("yt_reports.report_id", ondelete="SET NULL")),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("data", JSON, nullable=False, server_default=EMPTY),  # angle, hook, why, format, evidence, thumbnail idea
        sa.Column("status", sa.Text(), nullable=False, server_default="new"),  # new | saved | used | dismissed
        _now(),
        key="idea_id",
    )
    _protect("yt_ideas", "SELECT, INSERT, UPDATE")

    _base(
        "yt_drafts",
        sa.Column("video_id", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="running"),  # running | ready | applied | failed
        sa.Column("options", JSON, nullable=False, server_default=EMPTY),
        sa.Column("output", JSON),  # what the model wrote (three titles, description, tags, …)
        sa.Column("chosen", JSON),  # what the owner picked and edited; what is sent to YouTube
        sa.Column("seo", JSON),  # checks by code
        sa.Column("error", sa.Text()),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        _now(),
        _now("updated_at"),
        key="draft_id",
    )
    op.create_index("ix_yt_drafts_video", "yt_drafts", ["connection_id", "video_id", "created_at"])
    _protect("yt_drafts", "SELECT, INSERT, UPDATE")

    _base(
        "yt_thumbnails",
        sa.Column("video_id", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="ready"),  # working | ready | applied | failed
        sa.Column("spec", JSON, nullable=False, server_default=EMPTY),  # layout, texts, fonts, colours, effects
        sa.Column("background", JSON, nullable=False, server_default=EMPTY),  # where the background came from
        sa.Column("rev", sa.Integer(), nullable=False, server_default="1"),  # bumps when re-rendered
        sa.Column("error", sa.Text()),
        sa.Column("applied_at", sa.DateTime(timezone=True)),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        _now(),
        key="thumbnail_id",
    )
    _protect("yt_thumbnails", "SELECT, INSERT, UPDATE, DELETE")

    _base(
        "yt_replies",
        sa.Column("comment_id", sa.Text(), nullable=False),
        sa.Column("video_id", sa.Text()),
        sa.Column("author", sa.Text(), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("draft", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="new"),  # new | drafted | sent | dismissed
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        _now(),
        sa.UniqueConstraint("connection_id", "comment_id", name="uq_yt_replies_comment"),
        key="reply_id",
    )
    _protect("yt_replies", "SELECT, INSERT, UPDATE")


def downgrade() -> None:
    for t in ("yt_replies", "yt_thumbnails", "yt_drafts", "yt_ideas", "yt_competitors", "yt_reports",
              "yt_video_snapshots", "yt_videos", "yt_settings"):
        op.drop_table(t)
