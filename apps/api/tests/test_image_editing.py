"""AI photo edits (ADR 005): toggles, instructions, rights of the result, approval, fal.ai flow.

fal.ai is replaced by httpx.MockTransport: no real calls, no cost.
"""
import io
import json
from decimal import Decimal

import httpx
import pytest
from PIL import Image

from del_social.knowledge.brand_profile import BrandProfile, ImageEditing
from del_social.media import editing
from del_social.media.editing import EditKind, instruction, result_source
from del_social.media.fal import FalClient

from .conftest import O
from .test_media import jpeg, path_of, upload


def test_instructions_protect_the_product():
    bg = instruction(EditKind.BACKGROUND, "a bright Scandinavian living room", "the wardrobe", False)
    assert "Keep the wardrobe exactly as it is" in bg and "Scandinavian living room" in bg
    recolor = instruction(EditKind.RECOLOR, "walnut veneer", "", False)
    assert "the main furniture piece" in recolor and "Keep its exact shape" in recolor
    swap = instruction(EditKind.SWAP, "", "the sofa", True)
    assert "the product shown in the second image" in swap
    for text in (bg, recolor, swap, instruction(EditKind.REMOVE, "the chair", "", False)):
        assert "No text, letters, logos, watermarks or people" in text


@pytest.mark.parametrize("kind, parent, ref, expected", [
    (EditKind.ENHANCE, "own", None, "own"),
    (EditKind.REMOVE, "licensed", None, "licensed"),
    (EditKind.BACKGROUND, "own", None, "render"),
    (EditKind.BACKGROUND, "own", "reference", "render"),  # style reference only: product is still ours
    (EditKind.RECOLOR, "own", None, "render"),
    (EditKind.SWAP, "own", "own", "render"),
    (EditKind.SWAP, "own", "reference", "reference"),  # someone else's product inserted
    (EditKind.ENHANCE, "reference", None, "reference"),  # never becomes publishable
])
def test_result_source(kind, parent, ref, expected):
    assert result_source(kind, parent, ref) == expected


def test_toggles_default_off():
    settings = BrandProfile().image_editing
    assert not any(editing.allowed(settings, k) for k in EditKind)
    assert editing.allowed(ImageEditing(recolor=True), EditKind.RECOLOR)


async def test_translation_falls_back_to_original():
    from del_social.llm import LLMError

    class Broken:
        async def structured(self, **kw):
            raise LLMError("no credit")

    assert await editing.to_english(None, None, "otağı işıqlı et") == "otağı işıqlı et"
    assert await editing.to_english(Broken(), None, "otağı işıqlı et") == "otağı işıqlı et"
    assert await editing.to_english(Broken(), None, "plain English") == "plain English"


# --- API flow with a fake fal.ai ---


def result_jpeg(w=1200, h=1500) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (w, h), (180, 160, 140)).save(out, "JPEG")
    return out.getvalue()


class FakeFal:
    def __init__(self):
        self.submitted: list[tuple[str, dict]] = []
        self.auth: set[str] = set()
        self.polls = 0
        self.fail = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if request.url.host == "queue.fal.run":
            self.auth.add(request.headers.get("authorization", ""))
            if request.method == "POST":
                model = request.url.path.lstrip("/")
                self.submitted.append((model, json.loads(request.content)))
                base = f"https://queue.fal.run/{model}/requests/r{len(self.submitted)}"
                return httpx.Response(200, json={"request_id": "r", "status_url": base + "/status", "response_url": base})
            if url.endswith("/status"):
                self.polls += 1
                if self.fail:
                    return httpx.Response(200, json={"status": "COMPLETED", "error": "model crashed"})
                return httpx.Response(200, json={"status": "IN_PROGRESS" if self.polls % 2 else "COMPLETED"})
            key = "image" if "topaz" in url else "images"
            file = {"url": "https://v3.fal.media/files/out.jpg", "width": 1200, "height": 1500}
            return httpx.Response(200, json={key: file if key == "image" else [file]})
        if request.url.host == "v3.fal.media":
            return httpx.Response(200, content=result_jpeg())
        return httpx.Response(404)


@pytest.fixture
def fal(client):
    from del_social.main import app
    from del_social.routes.media import get_fal, get_translator

    fake = FakeFal()
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    app.dependency_overrides[get_fal] = lambda: FalClient(http, "fal-test-key", poll_seconds=0, timeout_seconds=5)
    app.dependency_overrides[get_translator] = lambda: None
    return fake


async def enable(client, tenant_id, headers, **toggles):
    profile = BrandProfile(image_editing=ImageEditing(**toggles)).model_dump(mode="json")
    current = (await client.get(f"/tenants/{tenant_id}/brand-profile", headers=headers)).json()["version"]
    r = await client.put(f"/tenants/{tenant_id}/brand-profile", json={"base_version": current, "data": profile}, headers={**headers, **O})
    assert r.status_code == 200, r.text


def media_url(tenant_id, path=""):
    return f"/tenants/{tenant_id}/media{path}"


async def test_edit_flow_with_approval(client, fal, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    photo = (await upload(client, tenants["a"], owner, jpeg(2000, 1600), description="Ağ qarderob")).json()
    body = {"kind": "background", "request": "a bright Scandinavian bedroom", "subject": "the wardrobe"}

    off = await client.post(media_url(tenants["a"], f"/{photo['asset_id']}/edits"), json=body, headers={**owner, **O})
    assert off.status_code == 403 and "turned off" in off.text
    await enable(client, tenants["a"], owner, background=True)

    r = await client.post(media_url(tenants["a"], f"/{photo['asset_id']}/edits"), json=body, headers={**owner, **O})
    assert r.status_code == 202, r.text
    assert r.json()["status"] == "pending" and r.json()["urls"] == {}

    model, sent = fal.submitted[0]
    assert model == "fal-ai/flux-2-pro/edit"
    assert "Scandinavian bedroom" in sent["prompt"] and "Keep the wardrobe exactly" in sent["prompt"]
    assert sent["image_urls"][0].startswith(f"https://api.test/media/{tenants['a']}/{photo['asset_id']}/full.jpg?")
    assert fal.auth == {"Key fal-test-key"}

    edited = next(m for m in (await client.get(media_url(tenants["a"]), headers=owner)).json() if m["parent_asset_id"])
    assert edited["status"] == "ready" and (edited["width"], edited["height"]) == (1200, 1500)
    assert edited["source"] == "render" and edited["edit"]["kind"] == "background"
    assert edited["edit"]["cost_usd"] == "0.0540"  # 1.8 MP × $0.03
    assert edited["publishable"] is False  # an AI edit needs a human OK first
    assert "prompt" not in edited["edit"]
    assert (await client.get(path_of(edited["urls"]["feed"]))).status_code == 200

    approved = await client.post(media_url(tenants["a"], f"/{edited['asset_id']}/approve"), headers={**owner, **O})
    assert approved.json()["publishable"] is True
    original = next(m for m in (await client.get(media_url(tenants["a"]), headers=owner)).json() if m["asset_id"] == photo["asset_id"])
    assert original["source"] == "own" and original["publishable"] is True  # the original is untouched

    usage = (await client.get(f"/tenants/{tenants['a']}/usage", headers=owner)).json()
    line = next(a for a in usage["by_agent"] if a["agent"] == "image_editor")
    assert line["calls"] == 1 and Decimal(line["cost_usd"]) == Decimal("0.054")


async def test_reference_products_are_never_publishable(client, fal, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    ours = (await upload(client, tenants["a"], owner, jpeg(2000, 1600))).json()
    pinterest = (await upload(client, tenants["a"], owner, jpeg(1600, 1600, color=(10, 90, 200)), source="reference")).json()
    assert pinterest["source"] == "reference" and pinterest["publishable"] is False
    await enable(client, tenants["a"], owner, swap_product=True)
    r = await client.post(
        media_url(tenants["a"], f"/{ours['asset_id']}/edits"),
        json={"kind": "swap", "subject": "the sofa", "reference_asset_id": pinterest["asset_id"]},
        headers={**owner, **O},
    )
    assert r.status_code == 202, r.text
    assert len(fal.submitted[0][1]["image_urls"]) == 2
    child = r.json()["asset_id"]
    await client.post(media_url(tenants["a"], f"/{child}/approve"), headers={**owner, **O})
    edited = next(m for m in (await client.get(media_url(tenants["a"]), headers=owner)).json() if m["asset_id"] == child)
    assert edited["source"] == "reference" and edited["publishable"] is False


async def test_enhance_uses_the_upscaler(client, fal, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    photo = (await upload(client, tenants["a"], owner, jpeg(1000, 1000))).json()
    await enable(client, tenants["a"], owner, enhance=True)
    r = await client.post(media_url(tenants["a"], f"/{photo['asset_id']}/edits"), json={"kind": "enhance"}, headers={**owner, **O})
    assert r.status_code == 202
    model, sent = fal.submitted[0]
    assert model == "fal-ai/topaz/upscale/image" and "/full.jpg?" in sent["image_url"] and "prompt" not in sent
    edited = next(m for m in (await client.get(media_url(tenants["a"]), headers=owner)).json() if m["asset_id"] == r.json()["asset_id"])
    assert edited["status"] == "ready" and edited["source"] == "own"
    assert edited["edit"]["cost_usd"] is None  # price not in our table: recorded as unknown, never guessed


async def test_failures_and_permissions(client, fal, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    viewer = await session_for(tenants["a_viewer"])
    photo = (await upload(client, tenants["a"], owner, jpeg(1200, 1200))).json()
    await enable(client, tenants["a"], owner, remove_objects=True)
    url = media_url(tenants["a"], f"/{photo['asset_id']}/edits")

    assert (await client.post(url, json={"kind": "remove", "request": "the chair"}, headers={**viewer, **O})).status_code == 403
    assert (await client.post(url, json={"kind": "remove", "request": "  "}, headers={**owner, **O})).status_code == 422

    fal.fail = True
    r = await client.post(url, json={"kind": "remove", "request": "the chair"}, headers={**owner, **O})
    edited = next(m for m in (await client.get(media_url(tenants["a"]), headers=owner)).json() if m["asset_id"] == r.json()["asset_id"])
    assert edited["status"] == "failed" and "model crashed" in edited["edit"]["error"] and edited["urls"] == {}
    assert (await client.post(media_url(tenants["a"], f"/{edited['asset_id']}/approve"), headers={**owner, **O})).status_code == 409

    from del_social.main import app
    from del_social.routes.media import get_fal

    app.dependency_overrides[get_fal] = lambda: None
    assert (await client.post(url, json={"kind": "remove", "request": "the chair"}, headers={**owner, **O})).status_code == 503
