"""Packages: the monthly allowance is enforced by code, owners ask for upgrades, the platform
admin assigns plans and sees billing numbers; no company sees another's package (ADR 007)."""
import uuid
from datetime import UTC, datetime

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.billing import quota
from del_social.connections.base import Identity
from del_social.connections.service import save_connection
from del_social.core.db import set_tenant
from del_social.models import Channel

from .conftest import O, as_app
from .test_agents import GOOD
from .test_posts import IG_ID, connect, product_with_photos, purl, world  # noqa: F401  (fixture)


@pytest.fixture
async def tiny_plan(admin):
    """A package small enough to hit every limit in a test."""
    await admin.execute(
        "INSERT INTO plans (plan_id, name, price_azn, posts_per_month, draft_factor, channels, users, video_credits, sort)"
        " VALUES ('tiny', 'Tiny', 170, 1, 2, 1, 2, 3, 99)"
    )
    yield "tiny"
    await admin.execute("DELETE FROM plan_requests WHERE plan_id = 'tiny'")
    await admin.execute("DELETE FROM subscriptions WHERE plan_id = 'tiny'")
    await admin.execute("DELETE FROM plans WHERE plan_id = 'tiny'")


@pytest.fixture
async def platform(account_factory, session_for):
    return await session_for(await account_factory(is_platform_admin=True))


async def assign(client, platform, tenant_id, plan_id, **extra):
    r = await client.put(f"/platform/tenants/{tenant_id}/subscription", json={"plan_id": plan_id, **extra}, headers={**platform, **O})
    assert r.status_code == 200, r.text
    return r.json()


async def plan_of(client, tenant_id, who):
    r = await client.get(f"/tenants/{tenant_id}/plan", headers=who)
    assert r.status_code == 200, r.text
    return r.json()


async def test_monthly_window_is_counted_from_the_start(admin):
    for starts, at in [("2026-01-31", "2026-03-15"), ("2026-09-27", "2026-09-27 10:00"), ("2026-02-10", "2027-02-09"),
                       ("2026-05-01", "2026-05-01")]:
        row = await admin.fetchrow(
            "SELECT period_start, period_end FROM subscription_period($1::text::timestamptz, $2::text::timestamptz)", starts, at
        )
        at_ts = await admin.fetchval("SELECT $1::text::timestamptz", at)
        assert row["period_start"] <= at_ts < row["period_end"], (starts, at, row)


async def test_posts_publish_and_draft_limits(client, world, admin, tenants, session_for, tiny_plan, platform):  # noqa: F811
    owner = await session_for(tenants["a_owner"])
    world.llm.copy_script = [[GOOD, GOOD, GOOD]]  # every post gets three good options
    await connect(admin, world.vault, tenants["a"], "instagram", IG_ID)
    await assign(client, platform, tenants["a"], "tiny", extra_video_credits=2)
    product_id, _ = await product_with_photos(client, tenants["a"], owner, n=1)

    info = await plan_of(client, tenants["a"], owner)
    assert info["state"] == "ok" and info["plan"]["plan_id"] == "tiny"
    assert info["posts"] == {"used": 0, "limit": 1} and info["drafts"] == {"used": 0, "limit": 2}
    assert info["channels"] == {"used": 1, "limit": 1} and info["video"] == {"used": 0, "limit": 5}
    assert "ai_cost" not in str(info) and "cost_usd" not in str(info)  # companies never see our dollar cost

    r = await client.post(purl(tenants["a"]), json={"product_id": product_id, "channels": ["instagram"]}, headers={**owner, **O})
    assert r.status_code == 202, r.text
    pub = await client.post(purl(tenants["a"], f"/{r.json()['post_id']}/approve"), json={"confirm": True}, headers={**owner, **O})
    assert pub.status_code == 202, pub.text
    info = await plan_of(client, tenants["a"], owner)
    assert info["posts"] == {"used": 1, "limit": 1} and info["posts_published"] == 1 and info["state"] == "limit"

    # The month's posts are used: no new post, and the Team Lead path gets the same answer
    r = await client.post(purl(tenants["a"]), json={"product_id": product_id}, headers={**owner, **O})
    assert r.status_code == 402 and r.json()["code"] == "posts"

    # A new package starts a new window; drafts are capped at draft_factor × posts
    await assign(client, platform, tenants["a"], "tiny")
    for _ in range(2):
        r = await client.post(purl(tenants["a"]), json={"product_id": product_id, "channels": ["instagram"]}, headers={**owner, **O})
        assert r.status_code == 202, r.text
    r = await client.post(purl(tenants["a"]), json={"product_id": product_id}, headers={**owner, **O})
    assert r.status_code == 402 and r.json()["code"] == "drafts"

    # Expired: nothing new starts, nothing new is approved
    waiting = (await client.get(purl(tenants["a"]), headers=owner)).json()[0]
    await admin.execute("UPDATE subscriptions SET expires_at = now() - interval '1 day' WHERE tenant_id = $1 AND status = 'active'", tenants["a"])
    assert (await plan_of(client, tenants["a"], owner))["state"] == "expired"
    r = await client.post(purl(tenants["a"], f"/{waiting['post_id']}/approve"), json={"confirm": True}, headers={**owner, **O})
    assert r.status_code == 402 and r.json()["code"] == "expired"


async def test_channel_and_user_limits(client, app_engine, world, admin, tenants, session_for, tiny_plan, platform):  # noqa: F811
    owner = await session_for(tenants["a_owner"])
    await assign(client, platform, tenants["a"], "tiny")
    # Tenant A already has two members (owner + viewer): the tiny package allows two users
    r = await client.post(f"/tenants/{tenants['a']}/invitations", json={"email": f"{uuid.uuid4().hex}@x.test", "role": "viewer"},
                          headers={**owner, **O})
    assert r.status_code == 402 and r.json()["code"] == "users"

    async def add(external_id: str):
        async with AsyncSession(app_engine) as db, db.begin():
            await set_tenant(db, tenants["a"])
            await save_connection(db, world.vault, tenant_id=tenants["a"], channel=Channel.FACEBOOK,
                                  identity=Identity(external_id=external_id, display_name="Page"), token="t",
                                  connected_by=tenants["a_owner"])

    await add("page-1")
    await add("page-1")  # reconnecting the same page is not a new channel
    with pytest.raises(quota.QuotaError) as e:
        await add("page-2")
    assert e.value.code == "channels"


async def test_upgrade_request_and_platform_overview(client, admin, tenants, session_for, tiny_plan, platform):
    owner = await session_for(tenants["a_owner"])
    viewer = await session_for(tenants["a_viewer"])
    await assign(client, platform, tenants["a"], "tiny", months=1)
    info = await plan_of(client, tenants["a"], viewer)  # everyone in the company sees the package
    assert [p["plan_id"] for p in info["catalog"]][:3] == ["basic", "pro", "enterprise"]
    assert info["expires_at"] and info["open_request"] is None

    assert (await client.post(f"/tenants/{tenants['a']}/plan/requests", json={"plan_id": "pro"}, headers={**viewer, **O})).status_code == 403
    assert (await client.post(f"/tenants/{tenants['a']}/plan/requests", json={"plan_id": "gold"}, headers={**owner, **O})).status_code == 404
    r = await client.post(f"/tenants/{tenants['a']}/plan/requests", json={"plan_id": "pro", "message": "Daha çox post"}, headers={**owner, **O})
    assert r.status_code == 201 and r.json()["open_request"]["plan_id"] == "pro"

    # Only platform admins get the overview, with our real cost and margin
    assert (await client.get("/platform/tenants", headers=owner)).status_code == 403
    rows = {r["tenant_id"]: r for r in (await client.get("/platform/tenants", headers=platform)).json()}
    a = rows[str(tenants["a"])]
    assert a["plan_id"] == "tiny" and a["open_request_plan"] == "pro" and a["members"] == 2
    assert float(a["ai_cost_month_usd"]) == 0 and float(a["margin_month_usd"]) == 100.0  # 170 AZN / 1.7

    await assign(client, platform, tenants["a"], "pro", months=12)
    info = await plan_of(client, tenants["a"], owner)
    assert info["plan"]["plan_id"] == "pro" and info["open_request"] is None and info["posts"]["limit"] == 90
    assert (datetime.fromisoformat(info["expires_at"]) - datetime.now(UTC)).days >= 359

    # Company B sees only its own package, and the overview function refuses anyone else
    b = await plan_of(client, tenants["b"], await session_for(tenants["b_owner"]))
    assert b["plan"]["plan_id"] == "enterprise" and b["open_request"] is None and b["posts"]["limit"] is None
    async with as_app(admin, tenants["a"], tenants["a_owner"]) as conn:
        assert await conn.fetchval("SELECT count(*) FROM subscriptions WHERE tenant_id = $1", tenants["b"]) == 0
    with pytest.raises(asyncpg.InsufficientPrivilegeError):
        async with as_app(admin, tenants["a"], tenants["a_owner"]) as conn:
            await conn.fetch("SELECT * FROM platform_tenant_overview()")
