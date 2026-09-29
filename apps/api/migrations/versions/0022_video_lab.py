"""Video lab: uploaded and produced videos, and the jobs that make them (ADR 012)

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-29

- yt_media: a video file on the media volume: an upload (arriving in chunks), a render (cut,
  subtitles, Shorts, export) or an AI-generated clip. Files are deleted after `expires_at`.
  transcript: segments with start/end seconds, from the transcription model (times are data).
- yt_jobs: one piece of work on media (transcribe, cut, subtitles, shorts, export, generate, upload
  to YouTube) with its options, progress, result and the credits it was paid with.
- lab_cleanup(): expired lab files' ids, across companies, for the cleanup loop (ids only).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
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
        "yt_media",
        sa.Column("media_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),  # upload | render | generated
        sa.Column("status", sa.Text(), nullable=False, server_default="uploading"),  # uploading | ready | failed
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("expected_bytes", sa.BigInteger()),
        sa.Column("duration_s", sa.Float()),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("has_audio", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("transcript", postgresql.JSONB()),
        sa.Column("source_media_id", sa.Uuid(), sa.ForeignKey("yt_media.media_id", ondelete="SET NULL")),
        sa.Column("youtube_video_id", sa.Text()),  # after upload to YouTube
        sa.Column("error", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now() + interval '14 days'")),
        sa.CheckConstraint("kind IN ('upload', 'render', 'generated')", name="ck_yt_media_kind"),
        sa.CheckConstraint("status IN ('uploading', 'ready', 'failed')", name="ck_yt_media_status"),
    )
    op.create_index("ix_yt_media_tenant_created", "yt_media", ["tenant_id", "created_at"])
    _protect("yt_media", "SELECT, INSERT, UPDATE, DELETE")

    op.create_table(
        "yt_jobs",
        sa.Column("job_id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.tenant_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("media_id", sa.Uuid(), sa.ForeignKey("yt_media.media_id", ondelete="CASCADE")),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),  # queued | running | done | failed
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("options", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result", postgresql.JSONB()),
        sa.Column("credits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text()),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("accounts.account_id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('transcribe', 'cut', 'subtitles', 'shorts', 'export', 'generate', 'upload', 'captions')", name="ck_yt_jobs_kind"),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed')", name="ck_yt_jobs_status"),
    )
    op.create_index("ix_yt_jobs_tenant_created", "yt_jobs", ["tenant_id", "created_at"])
    _protect("yt_jobs", "SELECT, INSERT, UPDATE")

    op.execute("""
        CREATE FUNCTION lab_cleanup()
        RETURNS TABLE (tenant_id uuid, media_id uuid)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public, pg_temp AS $$
            SELECT m.tenant_id, m.media_id FROM yt_media m WHERE m.expires_at < now() ORDER BY m.expires_at LIMIT 200
        $$
    """)
    op.execute("REVOKE ALL ON FUNCTION lab_cleanup() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION lab_cleanup() TO {APP_ROLE}")

    op.execute("INSERT INTO credit_packs (pack_id, addon_id, credits, price_azn, sort) VALUES ('yt_3000', 'youtube', 3000, 290, 4)")


def downgrade() -> None:
    op.execute("DELETE FROM credit_packs WHERE pack_id = 'yt_3000'")
    op.execute("DROP FUNCTION lab_cleanup()")
    op.drop_table("yt_jobs")
    op.drop_table("yt_media")
