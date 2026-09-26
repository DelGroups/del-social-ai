"""Storing connections and turning them into adapter credentials (ADR 003).

The only place tokens are encrypted or decrypted. Runs inside a tenant-scoped
transaction (set_tenant), so RLS limits every query to the current tenant.
"""
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.connections.base import Credentials, Identity
from del_social.core.vault import TokenVault, connection_aad
from del_social.models import Channel, Connection, ConnectionStatus


async def save_connection(
    db: AsyncSession,
    vault: TokenVault,
    *,
    tenant_id: uuid.UUID,
    channel: Channel,
    identity: Identity,
    token: str,
    connected_by: uuid.UUID,
    token_expires_at: datetime | None = None,
) -> Connection:
    """Create the connection, or replace the token of the same account connected before."""
    conn = await db.scalar(
        select(Connection).where(
            Connection.channel == channel.value, Connection.external_id == identity.external_id
        )
    )
    if conn is None:
        conn = Connection(
            connection_id=uuid.uuid4(),
            tenant_id=tenant_id,
            channel=channel.value,
            external_id=identity.external_id,
        )
        db.add(conn)
    conn.display_name = identity.display_name
    conn.details = identity.details
    conn.token_ciphertext = vault.encrypt(token, aad=connection_aad(tenant_id, conn.connection_id))
    conn.token_expires_at = token_expires_at
    conn.status = ConnectionStatus.ACTIVE.value
    conn.last_error = None
    conn.last_checked_at = datetime.now(UTC)
    conn.connected_by = connected_by
    await db.flush()
    await db.refresh(conn)
    return conn


def credentials(vault: TokenVault, conn: Connection) -> Credentials:
    """Raises VaultError if the stored token can't be decrypted (wrong key, tampered row)."""
    token = vault.decrypt(conn.token_ciphertext, aad=connection_aad(conn.tenant_id, conn.connection_id))
    return Credentials(external_id=conn.external_id, token=token, details=dict(conn.details or {}))


async def record_check(db: AsyncSession, conn: Connection, error: str | None, identity: Identity | None) -> Connection:
    conn.last_checked_at = datetime.now(UTC)
    conn.status = ConnectionStatus.ERROR.value if error else ConnectionStatus.ACTIVE.value
    conn.last_error = error
    if identity is not None:
        conn.display_name = identity.display_name
    await db.flush()
    await db.refresh(conn)
    return conn
