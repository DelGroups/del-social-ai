"""Channel cards on the home page: one snapshot per channel per day, growth computed by code,
nothing sent to Meta while the owner's switch is off (ADR 011)."""
import os
from datetime import UTC, date, datetime, timedelta

import httpx

from del_social.connections import stats
from del_social.connections.meta import MetaClient
from del_social.core.vault import TokenVault

from .test_posts import IG_ID, PAGE_ID, connect

MORNING = datetime(2026, 9, 28, 5, 0, tzinfo=UTC)  # 09:00 in Baku


class Graph:
    def __init__(self):
        self.calls: list[str] = []
        self.followers = 1200

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v23.0/")
        self.calls.append(path)
        if path == IG_ID:
            return httpx.Response(200, json={
                "username": "del_furniture", "name": "Del Furniture", "followers_count": self.followers, "follows_count": 80,
                "media_count": 64, "profile_picture_url": "https://cdn.test/ig.jpg",
                "media": {"data": [{"like_count": 30, "comments_count": 6}, {"like_count": 18, "comments_count": 2}]},
            })
        if path == PAGE_ID:
            return httpx.Response(200, json={"name": "Del Furniture", "followers_count": 540, "fan_count": 500,
                                             "link": "https://facebook.com/delfurniture", "picture": {"data": {"url": "https://cdn.test/fb.jpg"}}})
        return httpx.Response(404, json={"error": {"message": "unknown"}})


def meta_with(graph: Graph, paused: bool = False) -> MetaClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(graph.handle))
    return MetaClient(http, app_id="app", app_secret="s", version="v23.0", paused=paused)


async def test_daily_snapshot_and_cards(client, admin, app_engine, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    vault, graph = TokenVault(os.urandom(32)), Graph()
    await connect(admin, vault, tenants["a"], "instagram", IG_ID)
    await connect(admin, vault, tenants["a"], "facebook", PAGE_ID)
    readers = stats.meta_readers(meta_with(graph))

    # Before 07:30 in Baku nothing is collected; after it, one snapshot per channel per day
    assert await stats.tick(engine=app_engine, vault=vault, readers=readers, now=MORNING.replace(hour=2)) == 0
    assert await stats.collect_tenant(app_engine, vault, readers, tenants["a"], MORNING) == 2
    assert await stats.collect_tenant(app_engine, vault, readers, tenants["a"], MORNING) == 0  # already done today
    assert len(graph.calls) == 2

    # A week ago the account had 1000 followers
    await admin.execute(
        "INSERT INTO channel_stats (tenant_id, connection_id, day, followers)"
        " SELECT tenant_id, connection_id, $2, 1000 FROM connections WHERE tenant_id = $1 AND channel = 'instagram'",
        tenants["a"], date(2026, 9, 21),
    )
    cards = {c["channel"]: c for c in (await client.get(f"/tenants/{tenants['a']}/channels", headers=owner)).json()}
    ig = cards["instagram"]
    assert ig["followers"] == 1200 and ig["posts"] == 64 and ig["growth_7d"] == 200
    assert ig["likes"] == 48 and ig["comments"] == 8 and ig["recent"] == 2
    assert ig["engagement_rate"] == round((48 + 8) / 2 / 1200 * 100, 2)  # per post, of followers
    assert ig["avatar"] == "https://cdn.test/ig.jpg" and ig["url"] == "https://instagram.com/del_furniture"
    assert [p["followers"] for p in ig["series"]] == [1000, 1200]
    assert cards["facebook"]["followers"] == 540 and cards["facebook"]["url"] == "https://facebook.com/delfurniture"
    assert not ig["paused"]

    # The other company sees none of it
    other = await session_for(tenants["b_owner"])
    assert (await client.get(f"/tenants/{tenants['b']}/channels", headers=other)).json() == []


async def test_meta_paused_keeps_last_numbers(client, admin, app_engine, tenants, session_for):
    vault, graph = TokenVault(os.urandom(32)), Graph()
    await connect(admin, vault, tenants["a"], "instagram", IG_ID)
    assert stats.meta_readers(meta_with(graph, paused=True)) == {}
    assert await stats.tick(engine=app_engine, vault=vault, readers={}, now=MORNING) == 0
    assert graph.calls == []  # not one request to Meta


def test_growth_uses_the_closest_earlier_snapshot():
    Row = type("Row", (), {})

    def row(d: int, f: int | None):
        r = Row()
        r.day, r.followers = date(2026, 9, 28) - timedelta(days=d), f
        return r

    rows = [row(0, 150), row(3, 130), row(9, 100), row(40, 50)]
    assert stats.growth(rows, 7) == 50
    assert stats.growth(rows, 30) == 100
    assert stats.growth(rows[:2], 7) is None  # no snapshot that old yet
