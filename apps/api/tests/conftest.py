"""Test database fixtures.

TEST_DATABASE_URL must point at a disposable database whose name contains "test",
connecting as a superuser (or BYPASSRLS role) so fixtures can seed across tenants.
Queries under test run as the restricted app role via SET LOCAL ROLE.
"""
import os
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import asyncpg
import pytest

from del_social.core.db import APP_ROLE

API_DIR = Path(__file__).resolve().parents[1]


def plain_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


@pytest.fixture(scope="session")
def db_url() -> str:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.fail("TEST_DATABASE_URL is not set; the RLS isolation tests must never be skipped")
    db_name = url.rsplit("/", 1)[-1].split("?", 1)[0]
    if "test" not in db_name:
        pytest.fail(f"Refusing to run against database {db_name!r}: name must contain 'test'")
    return url


@pytest.fixture(scope="session")
def migrated_db(db_url: str) -> str:
    # Subprocess: runs exactly like production (`alembic upgrade head`) and keeps
    # Alembic's own event loop away from pytest-asyncio's.
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=API_DIR,
        env={**os.environ, "MIGRATION_DATABASE_URL": db_url},
        check=True,
    )
    return db_url


@pytest.fixture
async def admin(migrated_db: str) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(plain_dsn(migrated_db))
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def tenants(admin: asyncpg.Connection) -> AsyncIterator[dict[str, uuid.UUID]]:
    """Two tenants, two users each, one secret each. Removed afterwards."""
    a, b = uuid.uuid4(), uuid.uuid4()
    await admin.executemany(
        "INSERT INTO tenants (tenant_id, name) VALUES ($1, $2)",
        [(a, "Tenant A"), (b, "Tenant B")],
    )
    await admin.executemany(
        "INSERT INTO users (tenant_id, email, role) VALUES ($1, $2, $3)",
        [
            (a, f"owner-{a}@a.test", "owner"),
            (a, f"viewer-{a}@a.test", "viewer"),
            (b, f"owner-{b}@b.test", "owner"),
            (b, f"approver-{b}@b.test", "approver"),
        ],
    )
    await admin.executemany(
        "INSERT INTO tenant_secrets (tenant_id, key, encrypted_value) VALUES ($1, $2, $3)",
        [(a, "meta_token", b"ciphertext-a"), (b, "meta_token", b"ciphertext-b")],
    )
    try:
        yield {"a": a, "b": b}
    finally:
        ids = [a, b]
        await admin.execute("DELETE FROM tenant_secrets WHERE tenant_id = ANY($1::uuid[])", ids)
        await admin.execute("DELETE FROM users WHERE tenant_id = ANY($1::uuid[])", ids)
        await admin.execute("DELETE FROM tenants WHERE tenant_id = ANY($1::uuid[])", ids)


@asynccontextmanager
async def as_app(
    conn: asyncpg.Connection, tenant_id: uuid.UUID | None = None
) -> AsyncIterator[asyncpg.Connection]:
    """One transaction as the restricted app role, optionally scoped to a tenant."""
    async with conn.transaction():
        await conn.execute(f"SET LOCAL ROLE {APP_ROLE}")
        if tenant_id is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
        yield conn
