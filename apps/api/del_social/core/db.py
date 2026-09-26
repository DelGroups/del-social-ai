import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

APP_ROLE = "del_app"  # restricted runtime role created in migration 0001


def make_engine(url: str) -> AsyncEngine:
    return create_async_engine(url, pool_pre_ping=True)


async def set_tenant(session: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Scope the current transaction to one tenant for RLS.

    Transaction-local (set_config(..., true)): it resets at commit/rollback, so a
    pooled connection can never leak one tenant's scope into the next request.
    Call it at the start of every transaction; without it, tenant tables return no rows.
    """
    await session.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": str(tenant_id)}
    )


async def set_account(session: AsyncSession, account_id: uuid.UUID) -> None:
    """Scope the current transaction to one signed-in account (ADR 002).

    Same rules as set_tenant(): transaction-local; unset means the account-scoped
    tables (accounts, auth_sessions, password_resets) return no rows.
    """
    await session.execute(
        text("SELECT set_config('app.account_id', :aid, true)"), {"aid": str(account_id)}
    )
