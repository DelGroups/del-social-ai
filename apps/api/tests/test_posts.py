"""Posts: compose from a product, captions by the agents, human choice, publish to IG + FB.

Meta's Graph API and the LLM are fakes: no real calls, nothing is published.
"""
import os
import uuid
from urllib.parse import parse_qs

import httpx
import pytest

from del_social.connections.meta import MetaClient
from del_social.core.vault import TokenVault, connection_aad

from .conftest import O
from .test_agents import CHEAP, GOOD, FakeLLM
from .test_media import jpeg, upload

APP_SECRET = "graph-test-secret"
IG_ID, PAGE_ID = "17841400000000001", "100000000000001"


class FakeGraph:
    def __init__(self):
        self.calls: list[tuple[str, str, dict]] = []  # method, path, params/form
        self.fail_facebook = False
        self.n = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v23.0/")
        form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()} if request.method == "POST" else dict(request.url.params)
        self.calls.append((request.method, path, form))
        self.n += 1
        if request.method == "GET":
            if form.get("fields", "").startswith("status_code"):
                return httpx.Response(200, json={"status_code": "FINISHED"})
            if form.get("fields") == "permalink":
                return httpx.Response(200, json={"permalink": "https://www.instagram.com/p/TEST/"})
            return httpx.Response(404, json={"error": {"message": "unknown"}})
        if path == f"{IG_ID}/media":
            if form.get("media_type") == "CAROUSEL":
                return httpx.Response(200, json={"id": "carousel-container"})
            return httpx.Response(200, json={"id": f"container-{self.n}"})
        if path == f"{IG_ID}/media_publish":
            return httpx.Response(200, json={"id": "ig-media-1"})
        if path == f"{PAGE_ID}/photos":
            if self.fail_facebook:
                return httpx.Response(400, json={"error": {"message": "(#200) Permissions error"}})
            if form.get("published") == "false":
                return httpx.Response(200, json={"id": f"photo-{self.n}"})
            return httpx.Response(200, json={"id": "photo-1", "post_id": f"{PAGE_ID}_post1"})
        if path == f"{PAGE_ID}/feed":
            return httpx.Response(200, json={"id": f"{PAGE_ID}_multi"})
        if path == PAGE_ID:
            return httpx.Response(200, json={"success": True})
        return httpx.Response(404, json={"error": {"message": "unknown path"}})

    def published(self, kind: str) -> int:
        return sum(1 for m, p, _ in self.calls if m == "POST" and p.endswith(kind))


@pytest.fixture
def world(client, admin, tenants):
    """Fake Graph + vault + writing agents wired into the app; IG and FB connected for tenant A."""
    from del_social.core.deps import get_meta_optional, get_vault_optional
    from del_social.main import app
    from del_social.routes.media import get_analyst

    graph = FakeGraph()
    http = httpx.AsyncClient(transport=httpx.MockTransport(graph.handle))
    vault = TokenVault(os.urandom(32))
    meta = MetaClient(http, app_id="app", app_secret=APP_SECRET, version="v23.0")
    llm = FakeLLM([[GOOD, CHEAP, GOOD], [GOOD]])
    app.dependency_overrides[get_meta_optional] = lambda: meta
    app.dependency_overrides[get_vault_optional] = lambda: vault
    app.dependency_overrides[get_analyst] = lambda: llm
    graph.vault, graph.llm, graph.conns = vault, llm, {}
    return graph


async def connect(admin, vault, tenant_id, channel, external_id) -> uuid.UUID:
    cid = uuid.uuid4()
    await admin.execute(
        "INSERT INTO connections (connection_id, tenant_id, channel, external_id, display_name, token_ciphertext)"
        " VALUES ($1, $2, $3, $4, $5, $6)",
        cid, tenant_id, channel, external_id, f"Del {channel}", vault.encrypt("page-token", aad=connection_aad(tenant_id, cid)),
    )
    return cid


async def product_with_photos(client, tenant_id, owner, n=3, reference_extra=False) -> tuple[str, list[str]]:
    p = (await client.post(f"/tenants/{tenant_id}/products", json={"name": "Wendy qarderobu"}, headers={**owner, **O})).json()
    ids = []
    for i in range(n):
        r = await upload(client, tenant_id, owner, jpeg(1920, 1080, color=(40 * i, 90, 90)),
                         product_id=p["product_id"], description=f"Wendy qarderobu, bucaq {i + 1}")
        ids.append(r.json()["asset_id"])
    if reference_extra:
        await upload(client, tenant_id, owner, jpeg(1200, 1200, color=(1, 2, 3)), product_id=p["product_id"], source="reference")
    return p["product_id"], ids


def purl(tenant_id, path=""):
    return f"/tenants/{tenant_id}/posts{path}"


async def test_compose_choose_and_publish_carousel(client, world, admin, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    await connect(admin, world.vault, tenants["a"], "instagram", IG_ID)
    await connect(admin, world.vault, tenants["a"], "facebook", PAGE_ID)
    product_id, ids = await product_with_photos(client, tenants["a"], owner, reference_extra=True)

    r = await client.post(purl(tenants["a"]), json={"product_id": product_id, "format": "landscape", "with_logo": False}, headers={**owner, **O})
    assert r.status_code == 202, r.text
    post = (await client.get(purl(tenants["a"], f"/{r.json()['post_id']}"), headers=owner)).json()
    assert post["status"] == "ready" and len(post["options"]) == 3
    assert [ph["asset_id"] for ph in post["photos"]] == ids  # reference photo left out, order kept
    assert all("/landscape.jpg?" in ph["url"] for ph in post["photos"])
    assert post["caption"] == post["options"][post["chosen_option"]]["caption"]
    brief_prompt = world.llm.users[0][1]
    assert "Wendy qarderobu, bucaq 1" in brief_prompt and "carousel post with 3 photos" in brief_prompt

    edited = post["options"][2]["caption"] + "\n\nYeni!"
    patched = await client.patch(purl(tenants["a"], f"/{post['post_id']}"), json={"chosen_option": 2, "caption": edited}, headers={**owner, **O})
    assert patched.json()["caption"] == edited

    viewer = await session_for(tenants["a_viewer"])
    assert (await client.post(purl(tenants["a"], f"/{post['post_id']}/publish"), json={"confirm": True}, headers={**viewer, **O})).status_code == 403
    assert (await client.post(purl(tenants["a"], f"/{post['post_id']}/publish"), json={"confirm": False}, headers={**owner, **O})).status_code == 422
    assert world.published("media_publish") == 0  # nothing went out yet

    pub = await client.post(purl(tenants["a"], f"/{post['post_id']}/publish"), json={"confirm": True}, headers={**owner, **O})
    assert pub.status_code == 202
    done = (await client.get(purl(tenants["a"], f"/{post['post_id']}"), headers=owner)).json()
    assert done["status"] == "published" and done["approved_at"] and done["published_at"]
    assert done["results"]["instagram"]["url"] == "https://www.instagram.com/p/TEST/"
    assert done["results"]["facebook"]["id"] == f"{PAGE_ID}_multi"

    ig_items = [f for m, p, f in world.calls if p == f"{IG_ID}/media" and f.get("is_carousel_item") == "true"]
    assert len(ig_items) == 3 and all("/landscape.jpg?" in f["image_url"] for f in ig_items)
    carousel = next(f for m, p, f in world.calls if f.get("media_type") == "CAROUSEL")
    assert carousel["caption"] == edited and len(carousel["children"].split(",")) == 3
    assert all(f["appsecret_proof"] and f["access_token"] == "page-token" for m, p, f in world.calls if m == "POST")
    fb_feed = next(f for m, p, f in world.calls if p == f"{PAGE_ID}/feed")
    assert fb_feed["message"] == edited and fb_feed["attached_media"].count("media_fbid") == 3

    again = await client.post(purl(tenants["a"], f"/{post['post_id']}/publish"), json={"confirm": True}, headers={**owner, **O})
    assert again.status_code == 409  # never published twice
    assert world.published("media_publish") == 1


async def test_photos_can_be_reordered_and_removed(client, world, admin, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    owner_b = await session_for(tenants["b_owner"])
    _, ids = await product_with_photos(client, tenants["a"], owner, n=3)
    post = (await client.post(purl(tenants["a"]), json={"asset_ids": ids}, headers={**owner, **O})).json()
    url = purl(tenants["a"], f"/{post['post_id']}")

    reordered = await client.patch(url, json={"asset_ids": [ids[2], ids[0]]}, headers={**owner, **O})
    assert reordered.status_code == 200
    assert [p["asset_id"] for p in reordered.json()["photos"]] == [ids[2], ids[0]]  # new cover, one removed
    assert (await client.patch(url, json={"asset_ids": [ids[0], ids[0]]}, headers={**owner, **O})).status_code == 422
    assert (await client.patch(url, json={"asset_ids": []}, headers={**owner, **O})).status_code == 422
    ref = (await upload(client, tenants["a"], owner, jpeg(1200, 1200), source="reference")).json()
    assert (await client.patch(url, json={"asset_ids": [ids[0], ref["asset_id"]]}, headers={**owner, **O})).status_code == 409
    b_photo = (await upload(client, tenants["b"], owner_b, jpeg(1200, 1200))).json()
    assert (await client.patch(url, json={"asset_ids": [b_photo["asset_id"]]}, headers={**owner, **O})).status_code == 409

    await connect(admin, world.vault, tenants["a"], "instagram", IG_ID)
    await connect(admin, world.vault, tenants["a"], "facebook", PAGE_ID)
    await client.post(purl(tenants["a"], f"/{post['post_id']}/publish"), json={"confirm": True}, headers={**owner, **O})
    items = [f["image_url"] for m, p, f in world.calls if p == f"{IG_ID}/media" and f.get("is_carousel_item") == "true"]
    assert [ids[2] in items[0], ids[0] in items[1]] == [True, True]  # published in the chosen order
    assert (await client.patch(url, json={"asset_ids": [ids[0]]}, headers={**owner, **O})).status_code == 409  # published: frozen


async def test_partial_failure_retries_only_what_failed(client, world, admin, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    await connect(admin, world.vault, tenants["a"], "instagram", IG_ID)
    await connect(admin, world.vault, tenants["a"], "facebook", PAGE_ID)
    _, ids = await product_with_photos(client, tenants["a"], owner, n=1)
    post = (await client.post(purl(tenants["a"]), json={"asset_ids": ids}, headers={**owner, **O})).json()

    world.fail_facebook = True
    await client.post(purl(tenants["a"], f"/{post['post_id']}/publish"), json={"confirm": True}, headers={**owner, **O})
    p = (await client.get(purl(tenants["a"], f"/{post['post_id']}"), headers=owner)).json()
    assert p["status"] == "partly_published" and "Permissions error" in p["results"]["facebook"]["error"]
    assert p["results"]["instagram"]["id"] == "ig-media-1"

    world.fail_facebook = False
    await client.post(purl(tenants["a"], f"/{post['post_id']}/publish"), json={"confirm": True}, headers={**owner, **O})
    p = (await client.get(purl(tenants["a"], f"/{post['post_id']}"), headers=owner)).json()
    assert p["status"] == "published" and p["results"]["facebook"]["id"] == f"{PAGE_ID}_post1"
    assert world.published("media_publish") == 1  # Instagram was not posted again


async def test_guards(client, world, admin, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    owner_b = await session_for(tenants["b_owner"])
    ref = (await upload(client, tenants["a"], owner, jpeg(1200, 1200), source="reference")).json()
    blocked = await client.post(purl(tenants["a"]), json={"asset_ids": [ref["asset_id"]]}, headers={**owner, **O})
    assert blocked.status_code == 409  # a reference image never goes into a post
    assert (await client.post(purl(tenants["a"]), json={}, headers={**owner, **O})).status_code == 422

    _, ids = await product_with_photos(client, tenants["a"], owner, n=1)
    post = (await client.post(purl(tenants["a"]), json={"asset_ids": ids, "channels": ["instagram"]}, headers={**owner, **O})).json()
    # No Instagram connection: publishing reports it instead of failing silently
    await client.post(purl(tenants["a"], f"/{post['post_id']}/publish"), json={"confirm": True}, headers={**owner, **O})
    p = (await client.get(purl(tenants["a"], f"/{post['post_id']}"), headers=owner)).json()
    assert p["status"] == "approved" and "No working instagram connection" in p["error"]
    # Tenant B sees nothing of A
    assert (await client.get(purl(tenants["b"]), headers=owner_b)).json() == []
    assert (await client.get(purl(tenants["b"], f"/{post['post_id']}"), headers=owner_b)).status_code == 404
    b_try = await client.post(purl(tenants["b"]), json={"asset_ids": ids}, headers={**owner_b, **O})
    assert b_try.status_code == 404


async def test_facebook_page_details(client, world, admin, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    fb = await connect(admin, world.vault, tenants["a"], "facebook", PAGE_ID)
    ig = await connect(admin, world.vault, tenants["a"], "instagram", IG_ID)
    body = {"about": "Fərdi ölçülü premium mebel", "website": "https://del-furniture.com/", "emails": "info@del-furniture.com, sales@del-furniture.com"}
    r = await client.post(f"/tenants/{tenants['a']}/connections/{fb}/page-profile", json=body, headers={**owner, **O})
    assert r.status_code == 204, r.text
    sent = next(f for m, p, f in world.calls if p == PAGE_ID)
    assert sent["about"] == body["about"] and sent["emails"] == '["info@del-furniture.com", "sales@del-furniture.com"]'
    r = await client.post(f"/tenants/{tenants['a']}/connections/{ig}/page-profile", json=body, headers={**owner, **O})
    assert r.status_code == 409
