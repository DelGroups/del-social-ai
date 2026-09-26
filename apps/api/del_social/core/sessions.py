"""Server-side login sessions (ADR 002). Only token hashes are stored."""
import ipaddress
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.db import set_account
from del_social.core.security import hash_token, new_token
from del_social.models import AuthSession

SESSION_COOKIE = "__Host-del_session"
SESSION_ABSOLUTE = timedelta(days=30)
SESSION_IDLE = timedelta(days=7)
TOUCH_INTERVAL = timedelta(minutes=1)  # don't write on every request


def _parse_ip(ip: str | None) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(ip) if ip else None
    except ValueError:
        return None


async def create_session(
    db: AsyncSession, account_id: uuid.UUID, user_agent: str | None = None, ip: str | None = None
) -> str:
    """Start a session and return the raw token (sent to the client once, never stored)."""
    token, token_hash = new_token()
    now = datetime.now(UTC)
    await set_account(db, account_id)
    db.add(
        AuthSession(
            account_id=account_id,
            token_hash=token_hash,
            expires_at=now + SESSION_ABSOLUTE,
            idle_expires_at=now + SESSION_IDLE,
            user_agent=(user_agent or "")[:512] or None,
            ip=_parse_ip(ip),
        )
    )
    await db.flush()
    return token


async def resolve_session(db: AsyncSession, token: str) -> uuid.UUID | None:
    """Return the account for a valid token and scope the transaction to it; else None."""
    token_hash = hash_token(token)
    account_id = await db.scalar(
        text("SELECT auth_session_account(:h)"), {"h": token_hash}
    )
    if account_id is None:
        return None
    await set_account(db, account_id)
    # Sliding idle timeout, never past the absolute expiry
    await db.execute(
        update(AuthSession)
        .where(
            AuthSession.token_hash == token_hash,
            AuthSession.last_seen_at < func.now() - TOUCH_INTERVAL,
        )
        .values(
            last_seen_at=func.now(),
            idle_expires_at=func.least(func.now() + SESSION_IDLE, AuthSession.expires_at),
        )
    )
    return account_id


async def revoke_session(db: AsyncSession, token: str) -> None:
    """Revoke one session. Requires the account context (call after resolve_session)."""
    await db.execute(
        update(AuthSession)
        .where(AuthSession.token_hash == hash_token(token), AuthSession.revoked_at.is_(None))
        .values(revoked_at=func.now())
    )


async def revoke_other_sessions(db: AsyncSession, keep_token: str | None = None) -> int:
    """Revoke all of the current account's sessions except `keep_token` (e.g. after a password change)."""
    stmt = update(AuthSession).where(AuthSession.revoked_at.is_(None))
    if keep_token is not None:
        stmt = stmt.where(AuthSession.token_hash != hash_token(keep_token))
    result = await db.execute(stmt.values(revoked_at=func.now()))
    return result.rowcount
