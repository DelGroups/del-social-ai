"""Connections: token vault, RLS on the connections table, Telegram and Meta flows (ADR 003).

Telegram and Meta are replaced by httpx.MockTransport: tests never call a real network.
"""
import base64
import hashlib
import hmac
import os
import uuid
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from del_social.connections import build_adapters
from del_social.connections.base import Credentials, NotConnected, NotSupported, TikTokAdapter
from del_social.connections.meta import MetaClient
from del_social.core.vault import TokenVault, VaultError, connection_aad, parse_key
from del_social.models import Channel

from .conftest import O, as_app

BOT_TOKEN = "123456789:" + "A" * 35
APP_SECRET = "test-app-secret"
PAGE_TOKEN = "page-token-111"


# --- vault ---


def test_vault_round_trip_and_binding():
    vault = TokenVault(os.urandom(32))
    aad = connection_aad(uuid.uuid4(), uuid.uuid4())
    blob = vault.encrypt("secret-token", aad=aad)
    assert b"secret-token" not in blob
    assert vault.decrypt(blob, aad=aad) == "secret-token"
    assert vault.encrypt("secret-token", aad=aad) != blob  # fresh nonce every time
    with pytest.raises(VaultError):
        vault.decrypt(blob, aad=connection_aad(uuid.uuid4(), uuid.uuid4()))  # copied to another row
    tampered = blob[:-1] + bytes([blob[-1] ^ 1])
    with pytest.raises(VaultError):
        vault.decrypt(tampered, aad=aad)
    with pytest.raises(VaultError):
        TokenVault(os.urandom(32)).decrypt(blob, aad=aad)  # wrong key
    with pytest.raises(VaultError):
        vault.decrypt(b"\x02" + blob[1:], aad=aad)  # unknown key version


def test_vault_key_formats():
    key = os.urandom(32)
    assert parse_key(key.hex()) == key
    assert parse_key(base64.b64encode(key).decode()) == key
    assert parse_key(base64.urlsafe_b64encode(key).decode()) == key
    for bad in ["", "not a key", "ab" * 16, base64.b64encode(os.urandom(16)).decode()]:
        with pytest.raises(VaultError):
            parse_key(bad)
    assert key.hex() not in repr(TokenVault(key))


def test_credentials_repr_hides_token():
    assert "tok" not in repr(Credentials(external_id="1", token="tok"))


# --- adapter stubs ---


async def test_stub_channels_are_not_connected():
    stub = TikTokAdapter()
    assert not stub.available
    assert stub.capabilities().publish is False
    with pytest.raises(NotConnected):
        await stub.check(Credentials(external_id="x", token="t"))
    with pytest.raises(NotSupported):
        await stub.publish(Credentials(external_id="x", token="t"), post=None)


def test_registry_covers_every_channel():
    adapters = build_adapters(httpx.AsyncClient(), None)
    assert set(adapters) == set(Channel)


# --- RLS ---


async def test_connections_only_own_tenant(admin, tenants):
    for key in ("a", "b"):
        await admin.execute(
            "INSERT INTO connections (tenant_id, channel, external_id, display_name, token_ciphertext)"
            " VALUES ($1, 'telegram', $2, '@bot', '\\x00')",
            tenants[key],
            f"bot-{key}",
        )
    async with as_app(admin, tenants["a"]) as conn:
        rows = await conn.fetch("SELECT tenant_id, external_id FROM connections")
        moved = await conn.execute("UPDATE connections SET display_name = 'x' WHERE tenant_id = $1", tenants["b"])
    assert [(r["tenant_id"], r["external_id"]) for r in rows] == [(tenants["a"], "bot-a")]
    assert moved == "UPDATE 0"


# --- HTTP: fake Telegram and Meta ---


class FakeNetwork:
    """Answers like Telegram and the Graph API. Flip the flags to simulate revoked tokens."""

    def __init__(self):
        self.telegram_ok = True
        self.meta_token_ok = True
        self.seen_urls: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen_urls.append(str(request.url))
        if request.url.host == "api.telegram.org":
            return self._telegram(request)
        return self._graph(request)

    def _telegram(self, request: httpx.Request) -> httpx.Response:
        if self.telegram_ok and request.url.path == f"/bot{BOT_TOKEN}/getMe":
            return httpx.Response(200, json={"ok": True, "result": {"id": 42, "username": "del_bot", "first_name": "Del"}})
        return httpx.Response(401, json={"ok": False, "description": "Unauthorized"})

    def _graph(self, request: httpx.Request) -> httpx.Response:
        q = dict(request.url.params)
        path = request.url.path.removeprefix("/v23.0/")
        err = httpx.Response(400, json={"error": {"message": "Invalid OAuth access token", "code": 190}})
        if path == "oauth/access_token":
            if q.get("code") == "good" and q.get("client_secret") == APP_SECRET:
                return httpx.Response(200, json={"access_token": "short-user"})
            if q.get("fb_exchange_token") == "short-user":
                return httpx.Response(200, json={"access_token": "long-user", "expires_in": 5184000})
            return err
        token = q.get("access_token", "")
        proof = hmac.new(APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
        if q.get("appsecret_proof") != proof or not self.meta_token_ok:
            return err
        if path == "me/accounts" and token == "long-user":
            return httpx.Response(200, json={"data": [
                {"id": "111", "name": "Del Furniture", "access_token": PAGE_TOKEN,
                 "instagram_business_account": {"id": "999", "username": "delfurniture"}},
                {"id": "222", "name": "Other Page", "access_token": "page-token-222"},
            ]})
        if path == "111" and token == PAGE_TOKEN:
            return httpx.Response(200, json={"id": "111", "name": "Del Furniture"})
        if path == "999" and token == PAGE_TOKEN:
            return httpx.Response(200, json={"id": "999", "username": "delfurniture"})
        return err


@pytest.fixture
def net(client):
    """Wire a test vault and the fake network into the app (the client fixture clears overrides)."""
    from del_social.core.deps import get_http, get_meta_optional, get_vault_optional
    from del_social.main import app

    fake = FakeNetwork()
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    fake.vault = TokenVault(os.urandom(32))
    fake.meta = MetaClient(http, app_id="app123", app_secret=APP_SECRET, version="v23.0")
    app.dependency_overrides[get_vault_optional] = lambda: fake.vault
    app.dependency_overrides[get_http] = lambda: http
    app.dependency_overrides[get_meta_optional] = lambda: fake.meta
    return fake


def url(tenant_id, path=""):
    return f"/tenants/{tenant_id}/connections{path}"


async def test_telegram_connect_stores_only_ciphertext(client, net, admin, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    r = await client.post(url(tenants["a"], "/telegram"), json={"bot_token": BOT_TOKEN}, headers={**owner, **O})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["channel"] == "telegram" and body["display_name"] == "@del_bot" and body["status"] == "active"
    assert BOT_TOKEN not in r.text
    assert not any(k in body for k in ("token", "token_ciphertext"))

    row = await admin.fetchrow(
        "SELECT connection_id, tenant_id, token_ciphertext FROM connections WHERE connection_id = $1",
        uuid.UUID(body["connection_id"]),
    )
    assert BOT_TOKEN.encode() not in row["token_ciphertext"]
    aad = connection_aad(row["tenant_id"], row["connection_id"])
    assert net.vault.decrypt(row["token_ciphertext"], aad=aad) == BOT_TOKEN

    listing = await client.get(url(tenants["a"]), headers=owner)
    assert BOT_TOKEN not in listing.text
    telegram = next(c for c in listing.json() if c["channel"] == "telegram")
    assert telegram["configured"] and telegram["available"]
    assert [c["connection_id"] for c in telegram["connections"]] == [body["connection_id"]]

    again = await client.post(url(tenants["a"], "/telegram"), json={"bot_token": BOT_TOKEN}, headers={**owner, **O})
    assert again.json()["connection_id"] == body["connection_id"]  # reconnect replaces, no duplicate


async def test_telegram_rejected_tokens(client, net, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    malformed = await client.post(url(tenants["a"], "/telegram"), json={"bot_token": "nope"}, headers={**owner, **O})
    assert malformed.status_code == 400
    assert not net.seen_urls  # never sent to Telegram
    net.telegram_ok = False
    rejected = await client.post(url(tenants["a"], "/telegram"), json={"bot_token": BOT_TOKEN}, headers={**owner, **O})
    assert rejected.status_code == 400
    assert BOT_TOKEN not in rejected.text


async def test_roles_and_tenants_are_enforced(client, net, tenants, session_for):
    owner_a = await session_for(tenants["a_owner"])
    viewer_a = await session_for(tenants["a_viewer"])
    owner_b = await session_for(tenants["b_owner"])
    created = await client.post(url(tenants["a"], "/telegram"), json={"bot_token": BOT_TOKEN}, headers={**owner_a, **O})
    cid = created.json()["connection_id"]

    assert (await client.get(url(tenants["a"]), headers=viewer_a)).status_code == 200
    for method, path in [("POST", "/telegram"), ("POST", f"/{cid}/test"), ("DELETE", f"/{cid}"), ("POST", "/meta/start")]:
        r = await client.request(method, url(tenants["a"], path), json={"bot_token": BOT_TOKEN}, headers={**viewer_a, **O})
        assert r.status_code == 403, (method, path)

    # Tenant B's owner: no access to A, and A's connection doesn't exist from inside B
    assert (await client.get(url(tenants["a"]), headers=owner_b)).status_code == 403
    assert (await client.post(url(tenants["b"], f"/{cid}/test"), headers={**owner_b, **O})).status_code == 404
    assert (await client.delete(url(tenants["b"], f"/{cid}"), headers={**owner_b, **O})).status_code == 404
    b_listing = (await client.get(url(tenants["b"]), headers=owner_b)).json()
    assert all(not c["connections"] for c in b_listing)

    no_origin = await client.post(url(tenants["a"], "/telegram"), json={"bot_token": BOT_TOKEN}, headers=owner_a)
    assert no_origin.status_code == 403


async def test_test_button_then_disconnect(client, net, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    cid = (await client.post(url(tenants["a"], "/telegram"), json={"bot_token": BOT_TOKEN}, headers={**owner, **O})).json()["connection_id"]

    ok = await client.post(url(tenants["a"], f"/{cid}/test"), headers={**owner, **O})
    assert ok.status_code == 200 and ok.json()["status"] == "active" and ok.json()["last_error"] is None

    net.telegram_ok = False  # the bot token was revoked in @BotFather
    broken = await client.post(url(tenants["a"], f"/{cid}/test"), headers={**owner, **O})
    assert broken.status_code == 200
    assert broken.json()["status"] == "error" and broken.json()["last_error"]

    assert (await client.delete(url(tenants["a"], f"/{cid}"), headers={**owner, **O})).status_code == 204
    listing = (await client.get(url(tenants["a"]), headers=owner)).json()
    assert all(not c["connections"] for c in listing)


async def test_test_button_with_wrong_vault_key(client, net, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    cid = (await client.post(url(tenants["a"], "/telegram"), json={"bot_token": BOT_TOKEN}, headers={**owner, **O})).json()["connection_id"]
    net.vault = TokenVault(os.urandom(32))  # key changed on the server
    from del_social.core.deps import get_vault_optional
    from del_social.main import app

    app.dependency_overrides[get_vault_optional] = lambda: net.vault
    r = await client.post(url(tenants["a"], f"/{cid}/test"), headers={**owner, **O})
    assert r.json()["status"] == "error" and "connect again" in r.json()["last_error"]


def _state_of(start_url: str) -> dict[str, str]:
    parsed = urlparse(start_url)
    return {k: v[0] for k, v in parse_qs(parsed.query).items()} | {"_path": parsed.path}


async def test_meta_flow_connects_page_and_instagram(client, net, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    start = await client.post(url(tenants["a"], "/meta/start"), headers={**owner, **O})
    assert start.status_code == 200
    q = _state_of(start.json()["url"])
    assert q["_path"] == "/v23.0/dialog/oauth"
    assert q["client_id"] == "app123"
    assert q["redirect_uri"] == "https://app.test/api/connections/meta/callback"
    assert "pages_manage_posts" in q["scope"] and "instagram_content_publish" in q["scope"]

    cb = await client.get(f"/connections/meta/callback?state={q['state']}&code=good", headers=owner)
    assert cb.status_code == 303
    location = cb.headers["location"]
    assert location.startswith(f"/t/{tenants['a']}/connections?meta=pick&pick=")
    pick = location.rsplit("=", 1)[1]
    assert "long-user" not in location and PAGE_TOKEN not in location

    replay = await client.get(f"/connections/meta/callback?state={q['state']}&code=good", headers=owner)
    assert replay.headers["location"] == "/?meta=expired"  # state is single use

    options = await client.get(url(tenants["a"], f"/meta/pick/{pick}"), headers=owner)
    assert options.status_code == 200
    assert PAGE_TOKEN not in options.text
    assert options.json()[0] == {
        "page_id": "111", "name": "Del Furniture", "instagram_id": "999", "instagram_username": "delfurniture",
    }
    assert options.json()[1]["instagram_id"] is None

    chosen = await client.post(url(tenants["a"], f"/meta/pick/{pick}"), json={"page_id": "111"}, headers={**owner, **O})
    assert chosen.status_code == 201, chosen.text
    assert {(c["channel"], c["display_name"]) for c in chosen.json()} == {
        ("facebook", "Del Furniture"), ("instagram", "@delfurniture"),
    }
    assert PAGE_TOKEN not in chosen.text
    gone = await client.get(url(tenants["a"], f"/meta/pick/{pick}"), headers=owner)
    assert gone.status_code == 410  # the page list (with tokens) is deleted after use

    for c in chosen.json():
        tested = await client.post(url(tenants["a"], f"/{c['connection_id']}/test"), headers={**owner, **O})
        assert tested.json()["status"] == "active", tested.text
    net.meta_token_ok = False
    tested = await client.post(url(tenants["a"], f"/{chosen.json()[0]['connection_id']}/test"), headers={**owner, **O})
    assert tested.json()["status"] == "error"
    assert tested.json()["last_error"] == "Invalid OAuth access token"


async def test_meta_callback_guards(client, net, tenants, session_for):
    owner_a = await session_for(tenants["a_owner"])
    owner_b = await session_for(tenants["b_owner"])
    back = f"/t/{tenants['a']}/connections"

    async def start() -> str:
        r = await client.post(url(tenants["a"], "/meta/start"), headers={**owner_a, **O})
        return _state_of(r.json()["url"])["state"]

    other_person = await client.get(f"/connections/meta/callback?state={await start()}&code=good", headers=owner_b)
    assert other_person.headers["location"] == f"{back}?meta=session"
    signed_out = await client.get(f"/connections/meta/callback?state={await start()}&code=good")
    assert signed_out.headers["location"] == f"{back}?meta=session"
    cancelled = await client.get(f"/connections/meta/callback?state={await start()}&error=access_denied", headers=owner_a)
    assert cancelled.headers["location"] == f"{back}?meta=cancelled"
    bad_code = await client.get(f"/connections/meta/callback?state={await start()}&code=forged", headers=owner_a)
    assert bad_code.headers["location"] == f"{back}?meta=error"
    unknown = await client.get("/connections/meta/callback?state=made-up&code=good", headers=owner_a)
    assert unknown.headers["location"] == "/?meta=expired"

    # A page list is readable only by the person who logged in, inside the same tenant
    ok = await client.get(f"/connections/meta/callback?state={await start()}&code=good", headers=owner_a)
    pick = ok.headers["location"].rsplit("=", 1)[1]
    assert (await client.get(url(tenants["b"], f"/meta/pick/{pick}"), headers=owner_b)).status_code == 404
    assert (await client.post(
        url(tenants["a"], f"/meta/pick/{pick}"), json={"page_id": "not-listed"}, headers={**owner_a, **O}
    )).status_code == 404


async def test_not_configured(client, net, tenants, session_for):
    from del_social.core.deps import get_meta_optional, get_vault_optional
    from del_social.main import app

    owner = await session_for(tenants["a_owner"])
    app.dependency_overrides[get_meta_optional] = lambda: None
    listing = {c["channel"]: c for c in (await client.get(url(tenants["a"]), headers=owner)).json()}
    assert not listing["facebook"]["configured"] and not listing["instagram"]["configured"]
    assert listing["telegram"]["configured"]
    assert not listing["tiktok"]["available"] and not listing["tiktok"]["configured"]
    assert (await client.post(url(tenants["a"], "/meta/start"), headers={**owner, **O})).status_code == 503
    stray = await client.get("/connections/meta/callback?state=x&code=y", headers=owner)
    assert stray.status_code == 303 and stray.headers["location"] == "/?meta=expired"  # never a raw error page

    app.dependency_overrides[get_vault_optional] = lambda: None
    r = await client.post(url(tenants["a"], "/telegram"), json={"bot_token": BOT_TOKEN}, headers={**owner, **O})
    assert r.status_code == 503
