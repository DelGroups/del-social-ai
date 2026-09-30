"""YouTube Studio tables (migration 0021, ADR 012). All are per company (RLS) and per channel."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


def _tenant() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("tenants.tenant_id", ondelete="RESTRICT"))


def _conn(pk: bool = False) -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("connections.connection_id", ondelete="CASCADE"), primary_key=pk)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now())


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))


class YtSettings(Base):
    __tablename__ = "yt_settings"

    connection_id: Mapped[uuid.UUID] = _conn(pk=True)
    tenant_id: Mapped[uuid.UUID] = _tenant()
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    updated_at: Mapped[datetime] = _now()


class YtVideo(Base):
    __tablename__ = "yt_videos"

    connection_id: Mapped[uuid.UUID] = _conn(pk=True)
    video_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[uuid.UUID] = _tenant()
    title: Mapped[str] = mapped_column(Text, server_default="")
    description: Mapped[str] = mapped_column(Text, server_default="")
    tags: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    category_id: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[int | None] = mapped_column(Integer)
    privacy: Mapped[str | None] = mapped_column(Text)
    publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_short: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    thumbnail_url: Mapped[str | None] = mapped_column(Text)
    views: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)
    has_captions: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    synced_at: Mapped[datetime] = _now()


class YtVideoSnapshot(Base):
    __tablename__ = "yt_video_snapshots"

    connection_id: Mapped[uuid.UUID] = _conn(pk=True)
    video_id: Mapped[str] = mapped_column(Text, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = _tenant()
    views: Mapped[int | None] = mapped_column(BigInteger)
    likes: Mapped[int | None] = mapped_column(BigInteger)
    comments: Mapped[int | None] = mapped_column(BigInteger)


class YtReport(Base):
    __tablename__ = "yt_reports"

    report_id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    connection_id: Mapped[uuid.UUID] = _conn()
    kind: Mapped[str] = mapped_column(Text)  # pulse | daily | review | ideas
    status: Mapped[str] = mapped_column(Text, server_default="running")
    period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    sources: Mapped[list[Any]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    credits: Mapped[int] = mapped_column(Integer, server_default="0")
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    error: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class YtCompetitor(Base):
    __tablename__ = "yt_competitors"

    competitor_id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    connection_id: Mapped[uuid.UUID] = _conn()
    channel_id: Mapped[str] = mapped_column(Text)
    handle: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, server_default="")
    subscribers: Mapped[int | None] = mapped_column(BigInteger)
    videos: Mapped[int | None] = mapped_column(BigInteger)
    views: Mapped[int | None] = mapped_column(BigInteger)
    avatar: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, server_default="owner")
    status: Mapped[str] = mapped_column(Text, server_default="active")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()


class YtIdea(Base):
    __tablename__ = "yt_ideas"

    idea_id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    connection_id: Mapped[uuid.UUID] = _conn()
    report_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("yt_reports.report_id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    status: Mapped[str] = mapped_column(Text, server_default="new")
    created_at: Mapped[datetime] = _now()


class YtDraft(Base):
    __tablename__ = "yt_drafts"

    draft_id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    connection_id: Mapped[uuid.UUID] = _conn()
    video_id: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="running")
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    output: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    chosen: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    seo: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class YtThumbnail(Base):
    __tablename__ = "yt_thumbnails"

    thumbnail_id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    connection_id: Mapped[uuid.UUID] = _conn()
    video_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="ready")
    spec: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    background: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    rev: Mapped[int] = mapped_column(Integer, server_default="1")
    error: Mapped[str | None] = mapped_column(Text)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()


class YtReply(Base):
    __tablename__ = "yt_replies"

    reply_id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    connection_id: Mapped[uuid.UUID] = _conn()
    comment_id: Mapped[str] = mapped_column(Text)
    video_id: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str] = mapped_column(Text, server_default="")
    text: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    draft: Mapped[str] = mapped_column(Text, server_default="")
    status: Mapped[str] = mapped_column(Text, server_default="new")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_by: Mapped[str | None] = mapped_column(Text)  # person | agent
    hold: Mapped[str | None] = mapped_column(Text)  # why it waits for a person: check | language | link | old | limit | error
    drafted_by: Mapped[str | None] = mapped_column(Text)  # agent = drafted automatically (counted for credits)
    created_at: Mapped[datetime] = _now()


class YtChat(Base):
    """A message between the owner and the YouTube team (role user | agent). RLS: tenant."""

    __tablename__ = "yt_chat"

    message_id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    role: Mapped[str] = mapped_column(Text)
    agent: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    author: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()


class YtMedia(Base):
    """A video file in the lab (upload, render or AI clip). Deleted after expires_at. RLS: tenant."""

    __tablename__ = "yt_media"

    media_id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="uploading")
    title: Mapped[str] = mapped_column(Text, server_default="")
    filename: Mapped[str] = mapped_column(Text)
    bytes: Mapped[int] = mapped_column(BigInteger, server_default="0")
    expected_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration_s: Mapped[float | None] = mapped_column()
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    has_audio: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    transcript: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    source_media_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("yt_media.media_id", ondelete="SET NULL"))
    youtube_video_id: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now() + interval '14 days'"))


class YtJob(Base):
    """One piece of lab work (transcribe, cut, subtitles, shorts, export, generate, upload). RLS: tenant."""

    __tablename__ = "yt_jobs"

    job_id: Mapped[uuid.UUID] = _id()
    tenant_id: Mapped[uuid.UUID] = _tenant()
    media_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("yt_media.media_id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    progress: Mapped[int] = mapped_column(Integer, server_default="0")
    options: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    credits: Mapped[int] = mapped_column(Integer, server_default="0")
    error: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
