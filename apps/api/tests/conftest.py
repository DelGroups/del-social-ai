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

import asyncio

import asyncpg
import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.core.db import APP_ROLE, make_engine

API_DIR = Path(__file__).resolve().parents[1]

# del_social.main reads settings at import. Tests override the DB/Redis dependencies,
# so these only need to be well-formed.
os.environ.setdefault("DATABASE_URL", os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://unused/unused_test"))
os.environ.setdefault("REDIS_URL", os.environ.get("TEST_REDIS_URL", "redis://unused:6379/15"))
os.environ.setdefault("APP_BASE_URL", "https://app.test")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("MEDIA_PUBLIC_URL", "https://api.test")
os.environ.setdefault("MEDIA_ROOT", os.path.join(os.environ.get("TMPDIR", "/tmp"), f"del-media-test-{os.getpid()}"))


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


APP_TEST_PASSWORD = "del_app_test"


@pytest.fixture(scope="session")
def app_db_url(migrated_db: str) -> str:
    """URL for the restricted del_app role, as the API uses in production (test cluster only)."""

    async def enable_login() -> None:
        conn = await asyncpg.connect(plain_dsn(migrated_db))
        try:
            await conn.execute(f"ALTER ROLE {APP_ROLE} LOGIN PASSWORD '{APP_TEST_PASSWORD}'")
        finally:
            await conn.close()

    asyncio.run(enable_login())
    url = make_url(migrated_db).set(username=APP_ROLE, password=APP_TEST_PASSWORD)
    return url.render_as_string(hide_password=False)


@pytest.fixture
async def app_engine(app_db_url: str) -> AsyncIterator[AsyncEngine]:
    engine = make_engine(app_db_url)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def redis() -> AsyncIterator[Redis]:
    url = os.environ.get("TEST_REDIS_URL")
    if not url:
        pytest.fail("TEST_REDIS_URL is not set; auth tests need a real Redis")
    client = Redis.from_url(url)
    try:
        yield client
    finally:
        await client.aclose()


@pytest.fixture
async def admin(migrated_db: str) -> AsyncIterator[asyncpg.Connection]:
    conn = await asyncpg.connect(plain_dsn(migrated_db))
    try:
        yield conn
    finally:
        await conn.close()


@pytest.fixture
async def account_factory(admin: asyncpg.Connection) -> AsyncIterator:
    """Create global accounts (bypassing RLS as admin); all are removed afterwards."""
    created: list[uuid.UUID] = []

    async def make(email: str | None = None, **fields) -> uuid.UUID:
        account_id = uuid.uuid4()
        await admin.execute(
            "INSERT INTO accounts (account_id, email, password_hash, is_active, is_platform_admin)"
            " VALUES ($1, $2, $3, $4, $5)",
            account_id,
            email or f"{account_id}@acc.test",
            fields.get("password_hash", "not-a-real-hash"),
            fields.get("is_active", True),
            fields.get("is_platform_admin", False),
        )
        created.append(account_id)
        return account_id

    try:
        yield make
    finally:
        # Memberships are removed by the tenant fixtures; sessions/resets cascade.
        await admin.execute("DELETE FROM accounts WHERE account_id = ANY($1::uuid[])", created)


@pytest.fixture
async def tenants(admin: asyncpg.Connection, account_factory) -> AsyncIterator[dict[str, uuid.UUID]]:
    """Two tenants with two members and one secret each. Removed afterwards.

    Keys: "a", "b" (tenant ids) and "a_owner", "a_viewer", "b_owner", "b_approver" (account ids).
    """
    a, b = uuid.uuid4(), uuid.uuid4()
    await admin.executemany(
        "INSERT INTO tenants (tenant_id, name) VALUES ($1, $2)",
        [(a, "Tenant A"), (b, "Tenant B")],
    )
    ids: dict[str, uuid.UUID] = {"a": a, "b": b}
    for key, tenant, role in [
        ("a_owner", a, "owner"),
        ("a_viewer", a, "viewer"),
        ("b_owner", b, "owner"),
        ("b_approver", b, "approver"),
    ]:
        ids[key] = await account_factory()
        await admin.execute(
            "INSERT INTO memberships (tenant_id, account_id, role) VALUES ($1, $2, $3)",
            tenant,
            ids[key],
            role,
        )
    await admin.executemany(
        "INSERT INTO tenant_secrets (tenant_id, key, encrypted_value) VALUES ($1, $2, $3)",
        [(a, "meta_token", b"ciphertext-a"), (b, "meta_token", b"ciphertext-b")],
    )
    try:
        yield ids
    finally:
        tids = [a, b]
        for table in ("media_assets", "eval_items", "eval_runs", "llm_calls", "brand_profiles", "connections", "invitations", "memberships", "tenant_secrets", "tenants"):
            await admin.execute(f"DELETE FROM {table} WHERE tenant_id = ANY($1::uuid[])", tids)


@asynccontextmanager
async def as_app(
    conn: asyncpg.Connection,
    tenant_id: uuid.UUID | None = None,
    account_id: uuid.UUID | None = None,
) -> AsyncIterator[asyncpg.Connection]:
    """One transaction as the restricted app role, optionally scoped to a tenant and/or account."""
    async with conn.transaction():
        await conn.execute(f"SET LOCAL ROLE {APP_ROLE}")
        if tenant_id is not None:
            await conn.execute("SELECT set_config('app.tenant_id', $1, true)", str(tenant_id))
        if account_id is not None:
            await conn.execute("SELECT set_config('app.account_id', $1, true)", str(account_id))
        yield conn


# --- HTTP client through the real app (routes and connections tests) ---

ORIGIN = "https://app.test"
O = {"origin": ORIGIN}


def cookie(token: str) -> dict[str, str]:
    from del_social.core.sessions import SESSION_COOKIE

    return {"cookie": f"{SESSION_COOKIE}={token}"}


@pytest.fixture
async def client(app_engine, redis) -> AsyncIterator[httpx.AsyncClient]:
    # Imported here: del_social.main reads settings at import, after the env defaults above
    from del_social.core.deps import allowed_origins, get_db, get_redis
    from del_social.main import app

    async def db_override() -> AsyncIterator[AsyncSession]:
        async with AsyncSession(app_engine, expire_on_commit=False) as session, session.begin():
            yield session

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[allowed_origins] = lambda: [ORIGIN]
    b = uuid.uuid4().bytes  # fresh client IP per test so IP rate limits don't leak across tests
    transport = httpx.ASGITransport(app=app, client=(f"10.{b[0]}.{b[1]}.{b[2]}", 1234))
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def session_for(app_engine):
    from del_social.core.sessions import create_session

    async def make(account_id: uuid.UUID) -> dict[str, str]:
        async with AsyncSession(app_engine) as db, db.begin():
            return cookie(await create_session(db, account_id))

    return make
