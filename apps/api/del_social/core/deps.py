"""FastAPI dependencies: one DB transaction per request, session → account → membership (ADR 002)."""
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.connections.meta import MetaClient
from del_social.core.config import get_settings
from del_social.core.db import make_engine, set_tenant
from del_social.core.rate_limit import RateLimiter
from del_social.core.sessions import SESSION_COOKIE, resolve_session
from del_social.core.vault import TokenVault, parse_key
from del_social.models import Account, MemberRole, Membership
from del_social.tenants.permissions import Permission, has_permission

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


@dataclass(frozen=True)
class CurrentAccount:
    account_id: uuid.UUID
    email: str
    is_platform_admin: bool


@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID
    account: CurrentAccount
    role: MemberRole


@lru_cache
def _engine() -> AsyncEngine:
    return make_engine(get_settings().database_url)


@lru_cache
def _redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


def get_engine() -> AsyncEngine:
    """For work that outlives the request (background jobs open their own sessions)."""
    return _engine()


async def get_db() -> AsyncIterator[AsyncSession]:
    """The whole request runs in one transaction, so set_config scoping covers every query."""
    async with AsyncSession(_engine(), expire_on_commit=False) as session, session.begin():
        yield session


def get_redis() -> Redis:
    return _redis()


@lru_cache
def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(15.0), follow_redirects=False)


def get_http() -> httpx.AsyncClient:
    """Shared client for channel APIs (Meta, Telegram)."""
    return _http()


@lru_cache
def _vault() -> TokenVault | None:
    key = get_settings().token_vault_key
    return TokenVault(parse_key(key)) if key else None


def get_vault_optional() -> TokenVault | None:
    return _vault()


def get_vault(vault: TokenVault | None = Depends(get_vault_optional)) -> TokenVault:
    if vault is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Token vault is not configured")
    return vault


def get_meta_optional(http: httpx.AsyncClient = Depends(get_http)) -> MetaClient | None:
    s = get_settings()
    if not s.meta_configured:
        return None
    return MetaClient(
        http,
        app_id=s.meta_app_id,
        app_secret=s.meta_app_secret,
        version=s.meta_graph_version,
        login_config_id=s.meta_login_config_id,
    )


def get_meta(meta: MetaClient | None = Depends(get_meta_optional)) -> MetaClient:
    if meta is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The Meta app is not configured")
    return meta


def get_rate_limiter(redis: Redis = Depends(get_redis)) -> RateLimiter:
    return RateLimiter(redis)


def allowed_origins() -> list[str]:
    return get_settings().cors_origins


def check_origin(request: Request, origins: list[str] = Depends(allowed_origins)) -> None:
    """CSRF guard: state-changing requests must come from our own panel."""
    if request.method not in SAFE_METHODS and request.headers.get("origin") not in origins:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Origin not allowed")


async def current_account(
    request: Request,
    _: None = Depends(check_origin),
    db: AsyncSession = Depends(get_db),
) -> CurrentAccount:
    token = request.cookies.get(SESSION_COOKIE)
    account_id = await resolve_session(db, token) if token else None
    if account_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    account = await db.get(Account, account_id)  # RLS: visible because it's our own account
    return CurrentAccount(account.account_id, account.email, account.is_platform_admin)


async def tenant_member(
    tenant_id: uuid.UUID,
    account: CurrentAccount = Depends(current_account),
    db: AsyncSession = Depends(get_db),
) -> TenantContext:
    """The tenant in the URL is untrusted; the membership row is the proof of access."""
    await set_tenant(db, tenant_id)
    role = await db.scalar(
        select(Membership.role).where(Membership.account_id == account.account_id)
    )
    if role is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this tenant")
    return TenantContext(tenant_id, account, role)


def require_permission(permission: Permission) -> Callable:
    async def dependency(ctx: TenantContext = Depends(tenant_member)) -> TenantContext:
        if not has_permission(ctx.role, permission):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return ctx

    return dependency


async def require_platform_admin(
    account: CurrentAccount = Depends(current_account),
) -> CurrentAccount:
    if not account.is_platform_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Platform admin only")
    return account
