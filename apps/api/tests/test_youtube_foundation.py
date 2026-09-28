"""YouTube Studio foundation (ADR 012): the add-on and its credits, buying, and connecting a
channel with Google. Google is a fake; balances are always computed from the ledger."""
import asyncio
import os
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from del_social.billing import credits
from del_social.connections import stats
from del_social.connections.youtube import GoogleOAuth, QuotaMeter, YouTubeClient, YouTubeError
from del_social.core.db import set_tenant
from del_social.core.vault import TokenVault

from .conftest import O

CHANNEL = {
    "id": "UCcars123",
    "snippet": {"title": "Auto Baku", "customUrl": "@autobaku", "country": "AZ",
                "thumbnails": {"medium": {"url": "https://yt.test/avatar.jpg"}}},
    "statistics": {"subscriberCount": "104", "viewCount": "18650", "videoCount": "23", "hiddenSubscriberCount": False},
    "contentDetails": {"relatedPlaylists": {"uploads": "UUcars123"}},
}


class FakeGoogle:
    def __init__(self):
        self.calls: list[str] = []
        self.refresh_ok = True
        self.channels = [CHANNEL]

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(f"{request.method} {request.url.host}{request.url.path}")
        if request.url.host == "oauth2.googleapis.com" and request.url.path == "/token":
            form = parse_qs(request.content.decode())
            if form["grant_type"] == ["authorization_code"]:
                if form["code"] != ["good"]:
                    return httpx.Response(400, json={"error": "invalid_grant"})
                return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-secret", "expires_in": 3599,
                                                 "scope": "https://www.googleapis.com/auth/youtube.force-ssl https://www.googleapis.com/auth/yt-analytics.readonly"})
            if not self.refresh_ok:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3599})
        assert request.headers.get("authorization", "").startswith("Bearer at-")
        if request.url.path == "/youtube/v3/channels":
            return httpx.Response(200, json={"items": self.channels})
        return httpx.Response(404, json={"error": {"message": "unknown", "errors": [{"reason": "notFound"}]}})


@pytest.fixture
def google(client):
    from del_social.core.deps import get_http, get_vault_optional, get_youtube_optional
    from del_social.main import app

    fake = FakeGoogle()
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    fake.vault = TokenVault(os.urandom(32))
    fake.yt = YouTubeClient(http, GoogleOAuth(http, "cid", "csecret"), QuotaMeter(10_000))
    app.dependency_overrides[get_vault_optional] = lambda: fake.vault
    app.dependency_overrides[get_http] = lambda: http
    app.dependency_overrides[get_youtube_optional] = lambda: fake.yt
    return fake


@pytest.fixture
async def platform(account_factory, session_for):
    return await session_for(await account_factory(is_platform_admin=True))


async def addon_on(client, platform, tenant_id, months=1):
    r = await client.put(f"/platform/tenants/{tenant_id}/addons/youtube", json={"active": True, "months": months},
                         headers={**platform, **O})
    assert r.status_code == 200, r.text


def yt_status(plan: dict) -> dict:
    return next(a for a in plan["addons"] if a["addon_id"] == "youtube")


async def test_credits_monthly_first_then_bought_and_refunds(client, app_engine, tenants, session_for, platform):
    owner = await session_for(tenants["a_owner"])
    plan = (await client.get(f"/tenants/{tenants['a']}/plan", headers=owner)).json()
    assert yt_status(plan)["active"] is False and yt_status(plan)["total"] == 0

    # Asking for it; the platform admin turns it on and grants a pack
    r = await client.post(f"/tenants/{tenants['a']}/plan/purchases", json={"kind": "addon", "item_id": "youtube"}, headers={**owner, **O})
    assert r.status_code == 201 and yt_status(r.json())["open_request"] == "youtube"
    await addon_on(client, platform, tenants["a"])
    g = await client.post(f"/platform/tenants/{tenants['a']}/credits", json={"pack_id": "yt_100"}, headers={**platform, **O})
    assert g.json() == {"granted": 100, "total": 200}
    yt = yt_status((await client.get(f"/tenants/{tenants['a']}/plan", headers=owner)).json())
    assert yt["active"] and yt["monthly_left"] == 100 and yt["purchased"] == 100 and yt["open_request"] is None

    job = uuid.uuid4()
    async with AsyncSession(app_engine) as db, db.begin():
        await set_tenant(db, tenants["a"])
        rows = await credits.spend(db, tenants["a"], 150, "thumbnail_ai", job)
        assert [(r.bucket, r.delta) for r in rows] == [("monthly", -100), ("purchased", -50)]
        b = await credits.balance(db)
        assert (b.monthly_left, b.purchased, b.total) == (0, 50, 50)
        with pytest.raises(credits.CreditError) as e:
            await credits.spend(db, tenants["a"], 51, "review")
        assert e.value.code == "credits"
        assert await credits.refund(db, tenants["a"], job) == 150
        assert await credits.refund(db, tenants["a"], job) == 0  # only once
        assert (await credits.balance(db)).total == 200

    # The other company has none of it
    async with AsyncSession(app_engine) as db, db.begin():
        await set_tenant(db, tenants["b"])
        with pytest.raises(credits.CreditError) as e:
            await credits.spend(db, tenants["b"], 1, "metadata")
        assert e.value.code == "no_addon"


async def test_concurrent_spending_never_goes_below_zero(client, app_engine, tenants, platform):
    await addon_on(client, platform, tenants["a"])  # 100 monthly credits

    async def one() -> bool:
        async with AsyncSession(app_engine) as db, db.begin():
            await set_tenant(db, tenants["a"])
            try:
                await credits.spend(db, tenants["a"], 30, "review")
                return True
            except credits.CreditError:
                return False

    results = await asyncio.gather(*(one() for _ in range(6)))
    assert sum(results) == 3  # 3 × 30 = 90 ≤ 100 < 120


async def test_google_connects_a_youtube_channel(client, admin, google, tenants, session_for, platform):
    owner = await session_for(tenants["a_owner"])
    base = f"/tenants/{tenants['a']}/connections"
    no_addon = await client.post(f"{base}/google/start", headers={**owner, **O})
    assert no_addon.status_code == 402  # sold as an add-on

    await addon_on(client, platform, tenants["a"])
    # A YouTube-only company: no social package at all
    await admin.execute("UPDATE subscriptions SET status = 'ended' WHERE tenant_id = $1", tenants["a"])
    start = await client.post(f"{base}/google/start", headers={**owner, **O})
    assert start.status_code == 200, start.text
    q = {k: v[0] for k, v in parse_qs(urlparse(start.json()["url"]).query).items()}
    assert q["access_type"] == "offline" and "youtube.force-ssl" in q["scope"] and "yt-analytics.readonly" in q["scope"]
    assert q["redirect_uri"] == "https://app.test/api/connections/google/callback"

    bad = await client.get(f"/connections/google/callback?state={q['state']}&code=forged", headers=owner)
    assert bad.headers["location"] == f"/t/{tenants['a']}/connections?google=error"
    start = await client.post(f"{base}/google/start", headers={**owner, **O})
    state = parse_qs(urlparse(start.json()["url"]).query)["state"][0]
    cb = await client.get(f"/connections/google/callback?state={state}&code=good", headers=owner)
    assert cb.headers["location"] == f"/t/{tenants['a']}/youtube?connected=1"
    replay = await client.get(f"/connections/google/callback?state={state}&code=good", headers=owner)
    assert replay.headers["location"] == "/?google=expired"

    listing = (await client.get(base, headers=owner)).json()
    yt = next(c for c in listing if c["channel"] == "youtube")
    assert yt["available"] and yt["configured"]
    conn = yt["connections"][0]
    assert conn["display_name"] == "Auto Baku" and conn["external_id"] == "UCcars123"
    assert conn["details"]["handle"] == "@autobaku" and conn["details"]["uploads"] == "UUcars123"
    assert "rt-secret" not in str(listing)
    row = await admin.fetchrow("SELECT token_ciphertext FROM connections WHERE channel = 'youtube' AND tenant_id = $1", tenants["a"])
    assert b"rt-secret" not in row["token_ciphertext"]

    # A second channel is beyond what the add-on includes
    google.channels = [{**CHANNEL, "id": "UCother"}]
    start = await client.post(f"{base}/google/start", headers={**owner, **O})
    state = parse_qs(urlparse(start.json()["url"]).query)["state"][0]
    more = await client.get(f"/connections/google/callback?state={state}&code=good", headers=owner)
    assert more.headers["location"] == f"/t/{tenants['a']}/connections?google=channels"

    # Test button: Google refuses the refresh token → the connection needs to be made again
    google.yt._access.clear()
    google.refresh_ok = False
    tested = await client.post(f"{base}/{conn['connection_id']}/test", headers={**owner, **O})
    assert tested.json()["status"] == "error" and "connect the channel again" in tested.json()["last_error"]


async def test_youtube_numbers_for_the_home_card(app_engine, admin, google, tenants):
    from .test_posts import connect

    await connect(admin, google.vault, tenants["a"], "youtube", "UCcars123")
    readers = stats.youtube_readers(google.yt)
    assert await stats.collect_tenant(app_engine, google.vault, readers, tenants["a"]) == 1
    row = await admin.fetchrow("SELECT followers, posts, views, extra FROM channel_stats WHERE tenant_id = $1", tenants["a"])
    assert (row["followers"], row["posts"], row["views"]) == (104, 23, 18650)


def test_quota_meter_stops_before_the_budget_runs_out():
    m = QuotaMeter(1000)
    m.spend(50, "update")
    with pytest.raises(YouTubeError):
        m.spend(600, "search")  # search stops at 60 %
    for _ in range(17):
        m.spend(50, "update")
    with pytest.raises(YouTubeError):
        m.spend(50, "update")  # 900 = 90 % reached
    m.spend(1, "list")  # cheap reads continue
