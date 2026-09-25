import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, Text, UniqueConstraint, func, text
from sqlalchemy.orm import Mapped, mapped_column

from del_social.models.base import Base


class TenantSecret(Base):
    """Encrypted per-tenant secret (e.g. a channel token). Value is ciphertext, never plaintext."""

    __tablename__ = "tenant_secrets"
    __table_args__ = (UniqueConstraint("tenant_id", "key", name="uq_tenant_secrets_tenant_key"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, server_default=text("gen_random_uuid()")
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.tenant_id", ondelete="RESTRICT")
    )
    key: Mapped[str] = mapped_column(Text)
    encrypted_value: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
