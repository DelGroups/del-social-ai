import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class Task(Base):
    """One instruction turned into steps the agents walk through (a wizard that pauses for approval).

    steps: [{"key": "copy", "label": "...", "status": "pending|running|done|waiting|failed"}]. RLS: tenant.
    """

    __tablename__ = "tasks"

    task_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.tenant_id", ondelete="RESTRICT"))
    title: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="running")
    steps: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    post_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("posts.post_id", ondelete="RESTRICT"))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ChatMessage(Base):
    """A message in the Team Room. role=user (a person) or agent (team_lead, copywriter, …). RLS: tenant."""

    __tablename__ = "chat_messages"

    message_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.tenant_id", ondelete="RESTRICT"))
    role: Mapped[str] = mapped_column(Text)
    agent: Mapped[str | None] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.task_id", ondelete="RESTRICT"))
    post_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("posts.post_id", ondelete="RESTRICT"))
    author: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("accounts.account_id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentEvent(Base):
    """What an agent did, for the live team panel and the activity feed. RLS: tenant."""

    __tablename__ = "agent_events"

    event_id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    tenant_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tenants.tenant_id", ondelete="RESTRICT"))
    agent: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)  # started | finished | failed | info
    title: Mapped[str] = mapped_column(Text)
    task_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("tasks.task_id", ondelete="RESTRICT"))
    post_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("posts.post_id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
