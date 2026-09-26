"""Auth core against real Postgres (as del_app) and Redis: login, sessions, request dependencies."""
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
import pytest
from argon2 import PasswordHasher
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from del_social.core.auth import InvalidCredentials, RateLimited, authenticate
from del_social.core.deps import (
    CurrentAccount,
    TenantContext,
    allowed_origins,
    current_account,
    get_db,
    get_redis,
    require_permission,
    require_platform_admin,
)
from del_social.core.rate_limit import LOGIN_EMAIL_LIMIT, LOGIN_IP_LIMIT, RateLimiter, login_email_key
from del_social.core.security import hash_password, hash_token, verify_password
from del_social.core.sessions import (
    SESSION_COOKIE,
    create_session,
    resolve_session,
    revoke_other_sessions,
    revoke_session,
)
from del_social.tenants.permissions import Permission

PASSWORD = "correct horse battery"
ORIGIN = "https://app.test"


@asynccontextmanager
async def tx(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
        yield session


def random_ip() -> str:
    b = uuid.uuid4().bytes
    return f"10.{b[0]}.{b[1]}.{b[2]}"


@pytest.fixture
async def login_account(account_factory):
    """An account with a real password hash; returns (account_id, email)."""
    email = f"{uuid.uuid4()}@login.test"
    account_id = await account_factory(email, password_hash=hash_password(PASSWORD))
    return account_id, email


# --- authenticate ---


async def test_login_succeeds_case_insensitively(app_engine, redis, admin, login_account):
    account_id, email = login_account
    async with tx(app_engine) as db:
        got = await authenticate(db, RateLimiter(redis), f"  {email.upper()} ", PASSWORD, random_ip())
    assert got == account_id
    assert await admin.fetchval(
        "SELECT last_login_at IS NOT NULL FROM accounts WHERE account_id = $1", account_id
    )


async def test_every_failure_looks_the_same(app_engine, redis, account_factory, login_account):
    _, email = login_account
    inactive_email = f"{uuid.uuid4()}@login.test"
    await account_factory(inactive_email, password_hash=hash_password(PASSWORD), is_active=False)

    errors = []
    for attempt_email, attempt_password in [
        (email, "wrong password!"),  # wrong password
        (f"{uuid.uuid4()}@nobody.test", PASSWORD),  # unknown email
        (inactive_email, PASSWORD),  # right password, inactive account
    ]:
        with pytest.raises(InvalidCredentials) as exc:
            async with tx(app_engine) as db:
                await authenticate(db, RateLimiter(redis), attempt_email, attempt_password, None)
        errors.append((type(exc.value), str(exc.value)))
    assert len(set(errors)) == 1


async def test_email_rate_limit_blocks_even_correct_password(app_engine, redis, login_account):
    _, email = login_account
    limiter = RateLimiter(redis)
    for _ in range(LOGIN_EMAIL_LIMIT):
        with pytest.raises(InvalidCredentials):
            async with tx(app_engine) as db:
                await authenticate(db, limiter, email, "wrong password!", None)
    with pytest.raises(RateLimited):
        async with tx(app_engine) as db:
            await authenticate(db, limiter, email, PASSWORD, None)


async def test_ip_rate_limit_across_emails(app_engine, redis, login_account):
    _, email = login_account
    limiter = RateLimiter(redis)
    ip = random_ip()
    for _ in range(LOGIN_IP_LIMIT):
        with pytest.raises(InvalidCredentials):
            async with tx(app_engine) as db:
                await authenticate(db, limiter, f"{uuid.uuid4()}@spray.test", "wrong password!", ip)
    with pytest.raises(RateLimited):
        async with tx(app_engine) as db:
            await authenticate(db, limiter, email, PASSWORD, ip)
    # The same account from another IP still works
    async with tx(app_engine) as db:
        await authenticate(db, limiter, email, PASSWORD, random_ip())


async def test_success_clears_email_failures(app_engine, redis, login_account):
    _, email = login_account
    limiter = RateLimiter(redis)
    with pytest.raises(InvalidCredentials):
        async with tx(app_engine) as db:
            await authenticate(db, limiter, email, "wrong password!", None)
    assert await redis.get(login_email_key(email)) is not None
    async with tx(app_engine) as db:
        await authenticate(db, limiter, email, PASSWORD, None)
    assert await redis.get(login_email_key(email)) is None


async def test_weak_hash_is_upgraded_on_login(app_engine, redis, admin, account_factory):
    email = f"{uuid.uuid4()}@login.test"
    weak = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1).hash(PASSWORD)
    account_id = await account_factory(email, password_hash=weak)
    async with tx(app_engine) as db:
        await authenticate(db, RateLimiter(redis), email, PASSWORD, None)
    new_hash = await admin.fetchval("SELECT password_hash FROM accounts WHERE account_id = $1", account_id)
    assert new_hash != weak
    assert verify_password(PASSWORD, new_hash)


# --- sessions ---


async def test_session_roundtrip_stores_only_hash(app_engine, admin, tenants):
    async with tx(app_engine) as db:
        token = await create_session(db, tenants["a_owner"], "pytest", "10.0.0.1")
    stored = await admin.fetchval(
        "SELECT token_hash FROM auth_sessions WHERE account_id = $1", tenants["a_owner"]
    )
    assert stored == hash_token(token)
    async with tx(app_engine) as db:
        assert await resolve_session(db, token) == tenants["a_owner"]
        assert await resolve_session(db, "not-a-token") is None


async def test_revoked_session_stops_working(app_engine, tenants):
    async with tx(app_engine) as db:
        token = await create_session(db, tenants["a_owner"])
    async with tx(app_engine) as db:
        await resolve_session(db, token)
        await revoke_session(db, token)
    async with tx(app_engine) as db:
        assert await resolve_session(db, token) is None


async def test_revoke_other_sessions_keeps_current(app_engine, tenants):
    tokens = []
    for _ in range(3):
        async with tx(app_engine) as db:
            tokens.append(await create_session(db, tenants["a_owner"]))
    async with tx(app_engine) as db:
        await resolve_session(db, tokens[0])
        assert await revoke_other_sessions(db, keep_token=tokens[0]) == 2
    async with tx(app_engine) as db:
        assert await resolve_session(db, tokens[0]) == tenants["a_owner"]
        assert await resolve_session(db, tokens[1]) is None
        assert await resolve_session(db, tokens[2]) is None


async def test_cannot_revoke_someone_elses_session(app_engine, tenants):
    async with tx(app_engine) as db:
        mine = await create_session(db, tenants["a_owner"])
    async with tx(app_engine) as db:
        theirs = await create_session(db, tenants["b_owner"])
    async with tx(app_engine) as db:
        await resolve_session(db, mine)
        await revoke_session(db, theirs)
        assert await revoke_other_sessions(db, keep_token=mine) == 0
    async with tx(app_engine) as db:
        assert await resolve_session(db, theirs) == tenants["b_owner"]


async def test_idle_timeout_slides_but_never_past_absolute_expiry(app_engine, admin, tenants):
    async with tx(app_engine) as db:
        token = await create_session(db, tenants["a_owner"])
    h = hash_token(token)
    await admin.execute(
        "UPDATE auth_sessions SET last_seen_at = now() - interval '1 hour',"
        " idle_expires_at = now() + interval '1 minute' WHERE token_hash = $1",
        h,
    )
    async with tx(app_engine) as db:
        await resolve_session(db, token)
    assert await admin.fetchval(
        "SELECT idle_expires_at > now() + interval '6 days' FROM auth_sessions WHERE token_hash = $1", h
    )

    await admin.execute(
        "UPDATE auth_sessions SET last_seen_at = now() - interval '1 hour',"
        " expires_at = now() + interval '1 hour' WHERE token_hash = $1",
        h,
    )
    async with tx(app_engine) as db:
        await resolve_session(db, token)
    assert await admin.fetchval(
        "SELECT idle_expires_at = expires_at FROM auth_sessions WHERE token_hash = $1", h
    )


# --- request dependencies (through a real FastAPI app) ---


@pytest.fixture
async def client(app_engine, redis) -> AsyncIterator[httpx.AsyncClient]:
    app = FastAPI()

    @app.get("/me")
    async def me(account: CurrentAccount = Depends(current_account)):
        return {"account_id": str(account.account_id)}

    @app.get("/tenants/{tenant_id}/view")
    async def view(ctx: TenantContext = Depends(require_permission(Permission.VIEW))):
        return {"role": ctx.role.value}

    @app.post("/tenants/{tenant_id}/members")
    async def members(ctx: TenantContext = Depends(require_permission(Permission.MANAGE_MEMBERS))):
        return {"ok": True}

    @app.get("/platform")
    async def platform(account: CurrentAccount = Depends(require_platform_admin)):
        return {"ok": True}

    async def db_override() -> AsyncIterator[AsyncSession]:
        async with tx(app_engine) as session:
            yield session

    app.dependency_overrides[get_db] = db_override
    app.dependency_overrides[get_redis] = lambda: redis
    app.dependency_overrides[allowed_origins] = lambda: [ORIGIN]

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture
def session_for(app_engine):
    async def make(account_id: uuid.UUID) -> dict[str, str]:
        async with tx(app_engine) as db:
            token = await create_session(db, account_id)
        return {"cookie": f"{SESSION_COOKIE}={token}"}

    return make


async def test_requires_valid_session(client, tenants, session_for):
    assert (await client.get("/me")).status_code == 401
    assert (await client.get("/me", headers={"cookie": f"{SESSION_COOKIE}=bogus"})).status_code == 401
    r = await client.get("/me", headers=await session_for(tenants["a_owner"]))
    assert r.status_code == 200
    assert r.json() == {"account_id": str(tenants["a_owner"])}


async def test_revoked_session_is_rejected(client, app_engine, tenants):
    async with tx(app_engine) as db:
        token = await create_session(db, tenants["a_owner"])
    async with tx(app_engine) as db:
        await resolve_session(db, token)
        await revoke_session(db, token)
    r = await client.get("/me", headers={"cookie": f"{SESSION_COOKIE}={token}"})
    assert r.status_code == 401


async def test_member_of_a_cannot_enter_b(client, tenants, session_for):
    headers = await session_for(tenants["a_viewer"])
    own = await client.get(f"/tenants/{tenants['a']}/view", headers=headers)
    assert own.status_code == 200 and own.json() == {"role": "viewer"}
    assert (await client.get(f"/tenants/{tenants['b']}/view", headers=headers)).status_code == 403
    assert (await client.get(f"/tenants/{uuid.uuid4()}/view", headers=headers)).status_code == 403


async def test_role_is_enforced(client, tenants, session_for):
    url = f"/tenants/{tenants['a']}/members"
    viewer = await session_for(tenants["a_viewer"])
    owner = await session_for(tenants["a_owner"])
    assert (await client.post(url, headers=viewer | {"origin": ORIGIN})).status_code == 403
    assert (await client.post(url, headers=owner | {"origin": ORIGIN})).status_code == 200


@pytest.mark.parametrize("origin", [None, "https://evil.test"])
async def test_state_change_requires_our_origin(client, tenants, session_for, origin):
    headers = await session_for(tenants["a_owner"])
    if origin:
        headers["origin"] = origin
    r = await client.post(f"/tenants/{tenants['a']}/members", headers=headers)
    assert r.status_code == 403


async def test_platform_admin_only(client, tenants, account_factory, session_for):
    assert (await client.get("/platform", headers=await session_for(tenants["a_owner"]))).status_code == 403
    admin_id = await account_factory(is_platform_admin=True)
    assert (await client.get("/platform", headers=await session_for(admin_id))).status_code == 200
