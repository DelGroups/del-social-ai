import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class Tenant(Base):
    """A customer company. RLS: a session only sees the tenant in app.tenant_id."""

    __tablename__ = "tenants"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
