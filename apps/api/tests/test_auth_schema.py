"""Auth schema (ADR 002): account-scoped RLS and the pre-login SECURITY DEFINER functions."""
import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta

import asyncpg
import pytest

from del_social.core.db import APP_ROLE

from .conftest import as_app

ACCOUNT_TABLES = ("accounts", "auth_sessions", "password_resets")
DEFINER_FUNCTIONS = (
    "auth_login_lookup",
    "auth_session_account",
    "auth_my_memberships",
    "auth_invitation_by_token",
    "auth_password_reset_by_token",
    "auth_tenant_members",
)


def new_token_hash() -> bytes:
    return hashlib.sha256(os.urandom(32)).digest()


def in_(**delta) -> datetime:
    return datetime.now(UTC) + timedelta(**delta)


async def insert_session(admin, account_id, **overrides) -> bytes:
    fields = {
        "token_hash": new_token_hash(),
        "expires_at": in_(days=30),
        "idle_expires_at": in_(days=7),
        "revoked_at": None,
    } | overrides
    await admin.execute(
        "INSERT INTO auth_sessions (account_id, token_hash, expires_at, idle_expires_at, revoked_at)"
        " VALUES ($1, $2, $3, $4, $5)",
        account_id,
        fields["token_hash"],
        fields["expires_at"],
        fields["idle_expires_at"],
        fields["revoked_at"],
    )
    return fields["token_hash"]


async def insert_invitation(admin, tenant_id, email, **overrides) -> bytes:
    token_hash = overrides.get("token_hash", new_token_hash())
    await admin.execute(
        "INSERT INTO invitations (tenant_id, email, role, token_hash, expires_at, revoked_at)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        tenant_id,
        email,
        overrides.get("role", "viewer"),
        token_hash,
        overrides.get("expires_at", in_(days=7)),
        overrides.get("revoked_at"),
    )
    return token_hash


# --- accounts: each signed-in account sees and changes only itself ---


async def test_account_sees_only_itself(admin, tenants):
    async with as_app(admin, account_id=tenants["a_owner"]) as conn:
        rows = await conn.fetch("SELECT account_id FROM accounts")
    assert [r["account_id"] for r in rows] == [tenants["a_owner"]]


async def test_no_account_context_sees_nothing(admin, tenants):
    await insert_session(admin, tenants["a_owner"])
    async with as_app(admin) as conn:
        for table in ACCOUNT_TABLES:
            assert await conn.fetchval(f"SELECT count(*) FROM {table}") == 0, table


async def test_tenant_context_alone_does_not_expose_accounts(admin, tenants):
    """Being inside tenant A must not reveal A's members' account rows (emails, hashes)."""
    async with as_app(admin, tenant_id=tenants["a"]) as conn:
        assert await conn.fetchval("SELECT count(*) FROM accounts") == 0


@pytest.mark.parametrize("column", ["is_platform_admin", "is_active", "email"])
async def test_app_cannot_change_protected_columns_even_on_own_account(admin, tenants, column):
    """Column-level grants (0003): a bug in the app can't self-escalate or change identity."""
    value = {"is_platform_admin": "true", "is_active": "false", "email": "'x@evil.test'"}[column]
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with as_app(admin, account_id=tenants["a_owner"]) as conn:
            await conn.execute(
                f"UPDATE accounts SET {column} = {value} WHERE account_id = $1", tenants["a_owner"]
            )


async def test_app_cannot_create_platform_admin(admin, tenants):
    new_id = uuid.uuid4()
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with as_app(admin, account_id=new_id) as conn:
            await conn.execute(
                "INSERT INTO accounts (account_id, email, password_hash, is_platform_admin)"
                " VALUES ($1, $2, 'x', true)",
                new_id,
                f"{new_id}@evil.test",
            )


async def test_cannot_change_other_accounts_password(admin, tenants):
    async with as_app(admin, account_id=tenants["a_owner"]) as conn:
        result = await conn.execute(
            "UPDATE accounts SET password_hash = 'pwned' WHERE account_id = $1", tenants["b_owner"]
        )
    assert result == "UPDATE 0"
    assert await admin.fetchval(
        "SELECT password_hash FROM accounts WHERE account_id = $1", tenants["b_owner"]
    ) != "pwned"


async def test_cannot_insert_account_for_someone_else(admin, tenants):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with as_app(admin, account_id=tenants["a_owner"]) as conn:
            await conn.execute(
                "INSERT INTO accounts (account_id, email, password_hash) VALUES ($1, $2, 'x')",
                uuid.uuid4(),
                f"{uuid.uuid4()}@intruder.test",
            )


async def test_app_role_cannot_delete_accounts(admin, tenants):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with as_app(admin, account_id=tenants["a_owner"]) as conn:
            await conn.execute("DELETE FROM accounts")


async def test_sessions_only_own(admin, tenants):
    await insert_session(admin, tenants["a_owner"])
    await insert_session(admin, tenants["b_owner"])
    async with as_app(admin, account_id=tenants["a_owner"]) as conn:
        rows = await conn.fetch("SELECT account_id FROM auth_sessions")
    assert [r["account_id"] for r in rows] == [tenants["a_owner"]]


# --- auth_login_lookup ---


async def test_login_lookup_finds_one_account_case_insensitively(admin, account_factory):
    email = f"{uuid.uuid4()}@login.test"
    account_id = await account_factory(email)
    async with as_app(admin) as conn:
        rows = await conn.fetch("SELECT * FROM auth_login_lookup($1)", email.upper())
    assert len(rows) == 1
    assert list(rows[0].keys()) == ["account_id", "password_hash", "is_active"]
    assert rows[0]["account_id"] == account_id


async def test_login_lookup_unknown_email_returns_nothing(admin, tenants):
    async with as_app(admin) as conn:
        assert await conn.fetch("SELECT * FROM auth_login_lookup('nobody@nowhere.test')") == []


# --- auth_session_account ---


async def test_session_account_valid(admin, tenants):
    token_hash = await insert_session(admin, tenants["a_owner"])
    async with as_app(admin) as conn:
        assert await conn.fetchval("SELECT auth_session_account($1)", token_hash) == tenants["a_owner"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"revoked_at": in_(seconds=-1)},
        {"expires_at": in_(seconds=-1)},
        {"idle_expires_at": in_(seconds=-1)},
    ],
    ids=["revoked", "expired", "idle-expired"],
)
async def test_session_account_rejects_invalid(admin, tenants, overrides):
    token_hash = await insert_session(admin, tenants["a_owner"], **overrides)
    async with as_app(admin) as conn:
        assert await conn.fetchval("SELECT auth_session_account($1)", token_hash) is None


async def test_session_account_rejects_inactive_account(admin, account_factory):
    account_id = await account_factory(is_active=False)
    token_hash = await insert_session(admin, account_id)
    async with as_app(admin) as conn:
        assert await conn.fetchval("SELECT auth_session_account($1)", token_hash) is None


async def test_session_account_unknown_token(admin, tenants):
    async with as_app(admin) as conn:
        assert await conn.fetchval("SELECT auth_session_account($1)", new_token_hash()) is None


# --- auth_my_memberships ---


async def test_my_memberships_lists_every_tenant_of_that_account_only(admin, tenants, account_factory):
    shared = await account_factory()
    await admin.executemany(
        "INSERT INTO memberships (tenant_id, account_id, role) VALUES ($1, $2, $3)",
        [(tenants["a"], shared, "admin"), (tenants["b"], shared, "viewer")],
    )
    async with as_app(admin, account_id=shared) as conn:
        rows = await conn.fetch("SELECT tenant_id, tenant_name, role::text FROM auth_my_memberships()")
    assert {(r["tenant_id"], r["tenant_name"], r["role"]) for r in rows} == {
        (tenants["a"], "Tenant A", "admin"),
        (tenants["b"], "Tenant B", "viewer"),
    }

    async with as_app(admin, account_id=tenants["a_owner"]) as conn:
        rows = await conn.fetch("SELECT tenant_id FROM auth_my_memberships()")
    assert [r["tenant_id"] for r in rows] == [tenants["a"]]


async def test_my_memberships_without_account_is_empty(admin, tenants):
    async with as_app(admin) as conn:
        assert await conn.fetch("SELECT * FROM auth_my_memberships()") == []


# --- invitations ---


async def test_invitations_only_own_tenant(admin, tenants):
    await insert_invitation(admin, tenants["a"], "new-a@inv.test")
    await insert_invitation(admin, tenants["b"], "new-b@inv.test")
    async with as_app(admin, tenants["a"]) as conn:
        rows = await conn.fetch("SELECT email FROM invitations")
    assert [r["email"] for r in rows] == ["new-a@inv.test"]


async def test_one_pending_invitation_per_email_per_tenant(admin, tenants):
    await insert_invitation(admin, tenants["a"], "dup@inv.test")
    with pytest.raises(asyncpg.UniqueViolationError):
        await insert_invitation(admin, tenants["a"], "dup@inv.test")
    # Once revoked, the person can be invited again
    await admin.execute(
        "UPDATE invitations SET revoked_at = now() WHERE tenant_id = $1 AND email = 'dup@inv.test'",
        tenants["a"],
    )
    await insert_invitation(admin, tenants["a"], "dup@inv.test")


async def test_invitation_by_token(admin, tenants):
    token_hash = await insert_invitation(admin, tenants["a"], "join@inv.test", role="approver")
    async with as_app(admin) as conn:
        rows = await conn.fetch("SELECT * FROM auth_invitation_by_token($1)", token_hash)
        unknown = await conn.fetch("SELECT * FROM auth_invitation_by_token($1)", new_token_hash())
    assert len(rows) == 1
    row = rows[0]
    assert (row["tenant_id"], row["tenant_name"], row["email"], row["role"]) == (
        tenants["a"],
        "Tenant A",
        "join@inv.test",
        "approver",
    )
    assert unknown == []


# --- password resets ---


async def insert_reset(admin, account_id, **overrides) -> bytes:
    token_hash = new_token_hash()
    await admin.execute(
        "INSERT INTO password_resets (account_id, token_hash, expires_at, used_at)"
        " VALUES ($1, $2, $3, $4)",
        account_id,
        token_hash,
        overrides.get("expires_at", in_(hours=1)),
        overrides.get("used_at"),
    )
    return token_hash


async def test_password_reset_by_token(admin, tenants):
    valid = await insert_reset(admin, tenants["a_owner"])
    used = await insert_reset(admin, tenants["a_owner"], used_at=in_(seconds=-1))
    expired = await insert_reset(admin, tenants["a_owner"], expires_at=in_(seconds=-1))
    async with as_app(admin) as conn:
        assert await conn.fetchval("SELECT auth_password_reset_by_token($1)", valid) == tenants["a_owner"]
        assert await conn.fetchval("SELECT auth_password_reset_by_token($1)", used) is None
        assert await conn.fetchval("SELECT auth_password_reset_by_token($1)", expired) is None


# --- function hardening ---


async def test_definer_functions_are_hardened(admin, migrated_db):
    rows = await admin.fetch(
        """
        SELECT p.oid, p.proname, p.prosecdef, p.proconfig, p.proacl IS NULL AS default_acl,
               EXISTS (SELECT 1 FROM aclexplode(p.proacl) a WHERE a.grantee = 0) AS public_exec
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.proname LIKE 'auth\\_%'
        """
    )
    assert {r["proname"] for r in rows} == set(DEFINER_FUNCTIONS)
    for r in rows:
        name = r["proname"]
        assert r["prosecdef"], f"{name}: not SECURITY DEFINER"
        assert "search_path=public, pg_temp" in (r["proconfig"] or []), f"{name}: search_path not pinned"
        # NULL acl means the default, which lets PUBLIC execute
        assert not r["default_acl"] and not r["public_exec"], f"{name}: executable by PUBLIC"
        assert await admin.fetchval(
            "SELECT has_function_privilege($1, $2::oid, 'EXECUTE')", APP_ROLE, r["oid"]
        ), f"{name}: del_app cannot execute"


# --- auth_tenant_members ---


async def test_tenant_members_lists_current_tenant_only(admin, tenants):
    async with as_app(admin, tenant_id=tenants["a"]) as conn:
        rows = await conn.fetch("SELECT account_id, email, role::text FROM auth_tenant_members()")
        other = await conn.fetch("SELECT * FROM auth_tenant_members() WHERE account_id = $1", tenants["b_owner"])
    assert {(r["account_id"], r["role"]) for r in rows} == {
        (tenants["a_owner"], "owner"),
        (tenants["a_viewer"], "viewer"),
    }
    assert all(r["email"] for r in rows)
    assert other == []
    async with as_app(admin) as conn:
        assert await conn.fetch("SELECT * FROM auth_tenant_members()") == []
