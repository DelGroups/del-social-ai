"""Credential checking (ADR 002). Every failure looks the same to the caller."""
import uuid

from sqlalchemy import func, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.db import set_account
from del_social.core.rate_limit import (
    LOGIN_EMAIL_LIMIT,
    LOGIN_IP_LIMIT,
    LOGIN_WINDOW_SECONDS,
    RateLimiter,
    login_email_key,
    login_ip_key,
)
from del_social.core.security import burn_verify_time, hash_password, needs_rehash, verify_password
from del_social.models import Account


class InvalidCredentials(Exception):
    """Wrong email, wrong password or inactive account: deliberately indistinguishable."""


class RateLimited(Exception):
    pass


async def authenticate(
    db: AsyncSession, limiter: RateLimiter, email: str, password: str, ip: str | None
) -> uuid.UUID:
    """Check email + password and return the account id, scoping the transaction to it."""
    email = email.strip().lower()
    email_key = login_email_key(email)
    ip_key = login_ip_key(ip) if ip else None

    if await limiter.is_blocked(email_key, LOGIN_EMAIL_LIMIT) or (
        ip_key and await limiter.is_blocked(ip_key, LOGIN_IP_LIMIT)
    ):
        raise RateLimited

    row = (
        await db.execute(text("SELECT * FROM auth_login_lookup(:email)"), {"email": email})
    ).first()
    if row is None:
        burn_verify_time(password)
        ok = False
    else:
        ok = verify_password(password, row.password_hash) and row.is_active

    if not ok:
        await limiter.record(email_key, LOGIN_WINDOW_SECONDS)
        if ip_key:
            await limiter.record(ip_key, LOGIN_WINDOW_SECONDS)
        raise InvalidCredentials

    await limiter.reset(email_key)
    await set_account(db, row.account_id)
    values: dict = {"last_login_at": func.now()}
    if needs_rehash(row.password_hash):
        values["password_hash"] = hash_password(password)
    await db.execute(update(Account).where(Account.account_id == row.account_id).values(**values))
    return row.account_id
