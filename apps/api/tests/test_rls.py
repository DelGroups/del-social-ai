"""Tenant isolation: the Phase 0 definition of done. These must stay green on every deploy."""

import asyncpg
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.core.db import APP_ROLE, make_engine, set_tenant
from del_social.models import MemberRole, Membership, Tenant

from .conftest import as_app

TENANT_TABLES = {"tenants", "memberships", "tenant_secrets", "invitations", "connections", "brand_profiles", "llm_calls", "eval_runs", "eval_items", "media_assets", "products"}


# --- Reads: each tenant sees only its own rows ---


@pytest.mark.parametrize("me", ["a", "b"])
async def test_memberships_only_own_tenant(admin, tenants, me):
    async with as_app(admin, tenants[me]) as conn:
        rows = await conn.fetch("SELECT tenant_id FROM memberships")
    assert len(rows) == 2
    assert {r["tenant_id"] for r in rows} == {tenants[me]}


@pytest.mark.parametrize("me", ["a", "b"])
async def test_tenants_only_own_tenant(admin, tenants, me):
    async with as_app(admin, tenants[me]) as conn:
        rows = await conn.fetch("SELECT tenant_id FROM tenants")
    assert [r["tenant_id"] for r in rows] == [tenants[me]]


@pytest.mark.parametrize("me", ["a", "b"])
async def test_secrets_only_own_tenant(admin, tenants, me):
    async with as_app(admin, tenants[me]) as conn:
        rows = await conn.fetch("SELECT tenant_id FROM tenant_secrets")
    assert [r["tenant_id"] for r in rows] == [tenants[me]]


async def test_no_tenant_context_sees_nothing(admin, tenants):
    # Also proves the setting is transaction-local: the scoped block ends, the next sees nothing.
    async with as_app(admin, tenants["a"]):
        pass
    async with as_app(admin) as conn:
        for table in TENANT_TABLES:
            assert await conn.fetchval(f"SELECT count(*) FROM {table}") == 0, table


async def test_filtering_by_other_tenant_id_returns_nothing(admin, tenants):
    """Even a query that explicitly asks for tenant B gets nothing while scoped to A."""
    async with as_app(admin, tenants["a"]) as conn:
        n = await conn.fetchval(
            "SELECT count(*) FROM memberships WHERE tenant_id = $1", tenants["b"]
        )
    assert n == 0


# --- Writes: no crossing tenant boundaries ---


async def test_cannot_insert_into_other_tenant(admin, tenants):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with as_app(admin, tenants["a"]) as conn:
            await conn.execute(
                "INSERT INTO memberships (tenant_id, account_id) VALUES ($1, $2)",
                tenants["b"],
                tenants["a_owner"],
            )


async def test_cannot_move_row_to_other_tenant(admin, tenants):
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with as_app(admin, tenants["a"]) as conn:
            await conn.execute("UPDATE memberships SET tenant_id = $1", tenants["b"])


async def test_cannot_update_or_delete_other_tenant_rows(admin, tenants):
    async with as_app(admin, tenants["a"]) as conn:
        await conn.execute(
            "UPDATE memberships SET role = 'owner' WHERE tenant_id = $1", tenants["b"]
        )
        await conn.execute("DELETE FROM tenant_secrets WHERE tenant_id = $1", tenants["b"])
    b_roles = await admin.fetch(
        "SELECT role::text FROM memberships WHERE tenant_id = $1 ORDER BY role", tenants["b"]
    )
    assert sorted(r["role"] for r in b_roles) == ["approver", "owner"]
    assert await admin.fetchval(
        "SELECT count(*) FROM tenant_secrets WHERE tenant_id = $1", tenants["b"]
    ) == 1


async def test_insert_without_tenant_id_uses_context(admin, tenants):
    async with as_app(admin, tenants["a"]) as conn:
        row = await conn.fetchrow(
            "INSERT INTO memberships (account_id) VALUES ($1) RETURNING tenant_id",
            tenants["b_owner"],
        )
    assert row["tenant_id"] == tenants["a"]


async def test_insert_without_any_tenant_is_rejected(admin, tenants):
    # Postgres checks the RLS policy before NOT NULL; either one must stop the row.
    with pytest.raises((asyncpg.InsufficientPrivilegeError, asyncpg.NotNullViolationError)):
        async with as_app(admin) as conn:
            await conn.execute(
                "INSERT INTO memberships (account_id) VALUES ($1)", tenants["a_owner"]
            )


# --- Schema guards: future tables can't silently skip RLS ---


async def test_every_table_has_forced_rls_and_policy(admin, migrated_db):
    """Every application table, tenant-scoped or account-scoped, must be protected."""
    rows = await admin.fetch("""
        SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
               EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid) AS has_policy
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relname <> 'alembic_version'
    """)
    found = {r["relname"] for r in rows}
    assert TENANT_TABLES | {"accounts", "auth_sessions", "password_resets"} <= found
    for r in rows:
        assert r["relrowsecurity"], f"{r['relname']}: RLS not enabled"
        assert r["relforcerowsecurity"], f"{r['relname']}: RLS not forced"
        assert r["has_policy"], f"{r['relname']}: no policy"


async def test_app_role_cannot_bypass_rls(admin, migrated_db):
    role = await admin.fetchrow(
        "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = $1", APP_ROLE
    )
    assert role is not None
    assert not role["rolsuper"]
    assert not role["rolbypassrls"]


# --- ORM path: models + set_tenant() behave the same as raw SQL ---


async def test_orm_models_respect_rls(migrated_db, tenants):
    engine = make_engine(migrated_db)
    try:
        # expire_on_commit=False: objects stay readable after the transaction ends
        async with AsyncSession(engine, expire_on_commit=False) as session, session.begin():
            await session.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
            await set_tenant(session, tenants["a"])
            members = (await session.scalars(select(Membership))).all()
            visible_tenants = (await session.scalars(select(Tenant))).all()
    finally:
        await engine.dispose()

    assert len(members) == 2
    assert {m.tenant_id for m in members} == {tenants["a"]}
    assert {m.role for m in members} == {MemberRole.OWNER, MemberRole.VIEWER}
    assert [t.tenant_id for t in visible_tenants] == [tenants["a"]]
