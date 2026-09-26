"""AI photo edits configured per photo (ADR 005): recipes, combined instructions, rights, approval.

fal.ai is replaced by httpx.MockTransport: no real calls, no cost.
"""
import io
import json
import uuid
from decimal import Decimal

import httpx
import pytest
from PIL import Image

from del_social.media import editing
from del_social.media.editing import EditKind, Recipe, Step, instruction, result_source
from del_social.media.fal import FalClient

from .conftest import O
from .test_media import jpeg, path_of, upload

REF = uuid.uuid4()


# --- recipe logic ---


def test_combined_instruction_keeps_the_product():
    r = Recipe(
        subject="the wardrobe",
        remove=Step(on=True, request="the chair"),
        background=Step(on=True, request="a bright Scandinavian bedroom"),
        recolor=Step(on=True, request="walnut veneer"),
        enhance=True,
    )
    text = instruction(r, {EditKind.REMOVE: "the chair", EditKind.BACKGROUND: "a bright Scandinavian bedroom", EditKind.RECOLOR: "walnut veneer"})
    assert "Remove the chair" in text
    assert "colour or finish of the wardrobe to: walnut veneer" in text
    assert "surroundings with a bright Scandinavian bedroom" in text
    assert "Keep the wardrobe except for its colour or finish" in text
    assert "No text, letters, logos, watermarks or people" in text
    assert r.kinds() == [EditKind.REMOVE, EditKind.BACKGROUND, EditKind.RECOLOR, EditKind.ENHANCE]


def test_reference_images_are_numbered_in_order():
    style, product = uuid.uuid4(), uuid.uuid4()
    r = Recipe(
        subject="the sofa",
        background=Step(on=True, reference_asset_id=style),
        swap=Step(on=True, reference_asset_id=product),
    )
    text = instruction(r, {EditKind.BACKGROUND: "", EditKind.SWAP: ""})
    assert r.references() == [style, product]
    assert "style of the room in the second image" in text
    assert "Replace the sofa with the product shown in the third image" in text
    assert "Keep the sofa" not in text  # it is being replaced


def test_validation():
    with pytest.raises(editing.RecipeError, match="at least one"):
        editing.validate(Recipe())
    with pytest.raises(editing.RecipeError, match="recolor"):
        editing.validate(Recipe(recolor=Step(on=True)))
    editing.validate(Recipe(enhance=True))
    editing.validate(Recipe(swap=Step(on=True, reference_asset_id=REF)))  # described by the photo


@pytest.mark.parametrize("recipe, parent, refs, expected", [
    (Recipe(enhance=True), "own", {}, "own"),
    (Recipe(remove=Step(on=True, request="x")), "licensed", {}, "licensed"),
    (Recipe(background=Step(on=True, request="x")), "own", {}, "render"),
    (Recipe(background=Step(on=True, reference_asset_id=REF)), "own", {REF: "reference"}, "render"),
    (Recipe(recolor=Step(on=True, request="x")), "own", {}, "render"),
    (Recipe(swap=Step(on=True, reference_asset_id=REF)), "own", {REF: "own"}, "render"),
    (Recipe(swap=Step(on=True, reference_asset_id=REF)), "own", {REF: "reference"}, "reference"),
    (Recipe(enhance=True), "reference", {}, "reference"),
])
def test_result_source(recipe, parent, refs, expected):
    assert result_source(recipe, parent, refs) == expected


async def test_translation_falls_back_to_original():
    from del_social.llm import LLMError

    class Broken:
        async def structured(self, **kw):
            raise LLMError("no credit")

    assert await editing.to_english(None, None, "otağı işıqlı et") == "otağı işıqlı et"
    assert await editing.to_english(Broken(), None, "otağı işıqlı et") == "otağı işıqlı et"


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
            n = len(self.submitted)
            file = {"url": f"https://v3.fal.media/files/out{n}.jpg", "width": 1200, "height": 1500}
            return httpx.Response(200, json={"image": file} if "topaz" in url else {"images": [file]})
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


def media_url(tenant_id, path=""):
    return f"/tenants/{tenant_id}/media{path}"


async def listing(client, tenant_id, headers) -> dict[str, dict]:
    return {m["asset_id"]: m for m in (await client.get(media_url(tenant_id), headers=headers)).json()}


async def test_per_photo_recipe_is_saved_and_applied(client, fal, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    photo = (await upload(client, tenants["a"], owner, jpeg(2000, 1600), description="Ağ qarderob")).json()
    other = (await upload(client, tenants["a"], owner, jpeg(1600, 1600, color=(90, 90, 90)))).json()
    recipe = {
        "subject": "the wardrobe",
        "enhance": True,
        "remove": {"on": True, "request": "the chair"},
        "recolor": {"on": True, "request": "walnut veneer"},
    }

    saved = await client.put(media_url(tenants["a"], f"/{photo['asset_id']}/recipe"), json=recipe, headers={**owner, **O})
    assert saved.status_code == 200 and saved.json()["recipe"]["recolor"]["request"] == "walnut veneer"
    assert not fal.submitted  # saving settings runs nothing
    assert (await listing(client, tenants["a"], owner))[other["asset_id"]]["recipe"] is None  # per photo

    r = await client.post(media_url(tenants["a"], f"/{photo['asset_id']}/edits"), json=recipe, headers={**owner, **O})
    assert r.status_code == 202, r.text
    assert r.json()["edit"]["kinds"] == ["remove", "recolor", "enhance"]

    (m1, p1), (m2, p2) = fal.submitted
    assert m1 == "fal-ai/flux-2-pro/edit" and "Remove the chair" in p1["prompt"] and "walnut veneer" in p1["prompt"]
    assert p1["image_urls"][0].startswith(f"https://api.test/media/{tenants['a']}/{photo['asset_id']}/full.jpg?")
    assert m2 == "fal-ai/topaz/upscale/image" and p2["image_url"] == "https://v3.fal.media/files/out1.jpg"  # chained
    assert fal.auth == {"Key fal-test-key"}

    edited = (await listing(client, tenants["a"], owner))[r.json()["asset_id"]]
    assert edited["status"] == "ready" and edited["source"] == "render"
    assert edited["edit"]["models"] == ["fal-ai/flux-2-pro/edit", "fal-ai/topaz/upscale/image"]
    assert edited["edit"]["cost_usd"] == "0.0540" and edited["edit"]["cost_complete"] is False  # topaz price unknown
    assert edited["publishable"] is False  # needs a human OK
    assert (await client.get(path_of(edited["urls"]["feed"]))).status_code == 200

    approved = await client.post(media_url(tenants["a"], f"/{edited['asset_id']}/approve"), headers={**owner, **O})
    assert approved.json()["publishable"] is True
    original = (await listing(client, tenants["a"], owner))[photo["asset_id"]]
    assert original["source"] == "own" and original["publishable"] is True and original["recipe"]["enhance"] is True

    usage = (await client.get(f"/tenants/{tenants['a']}/usage", headers=owner)).json()
    line = next(a for a in usage["by_agent"] if a["agent"] == "image_editor")
    assert line["calls"] == 1 and Decimal(line["cost_usd"]) == Decimal("0.054")


async def test_enhance_only_uses_one_model(client, fal, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    photo = (await upload(client, tenants["a"], owner, jpeg(1000, 1000))).json()
    r = await client.post(media_url(tenants["a"], f"/{photo['asset_id']}/edits"), json={"enhance": True}, headers={**owner, **O})
    assert r.status_code == 202
    assert [m for m, _ in fal.submitted] == ["fal-ai/topaz/upscale/image"]
    assert "/full.jpg?" in fal.submitted[0][1]["image_url"]
    assert (await listing(client, tenants["a"], owner))[r.json()["asset_id"]]["source"] == "own"


async def test_reference_products_are_never_publishable(client, fal, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    ours = (await upload(client, tenants["a"], owner, jpeg(2000, 1600))).json()
    pinterest = (await upload(client, tenants["a"], owner, jpeg(1600, 1600, color=(10, 90, 200)), source="reference")).json()
    assert pinterest["source"] == "reference" and pinterest["publishable"] is False
    r = await client.post(
        media_url(tenants["a"], f"/{ours['asset_id']}/edits"),
        json={"subject": "the sofa", "swap": {"on": True, "reference_asset_id": pinterest["asset_id"]}},
        headers={**owner, **O},
    )
    assert r.status_code == 202, r.text
    assert len(fal.submitted[0][1]["image_urls"]) == 2
    await client.post(media_url(tenants["a"], f"/{r.json()['asset_id']}/approve"), headers={**owner, **O})
    edited = (await listing(client, tenants["a"], owner))[r.json()["asset_id"]]
    assert edited["source"] == "reference" and edited["publishable"] is False


async def test_failures_permissions_and_isolation(client, fal, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    viewer = await session_for(tenants["a_viewer"])
    owner_b = await session_for(tenants["b_owner"])
    photo = (await upload(client, tenants["a"], owner, jpeg(1200, 1200))).json()
    url = media_url(tenants["a"], f"/{photo['asset_id']}/edits")
    remove = {"remove": {"on": True, "request": "the chair"}}

    assert (await client.post(url, json=remove, headers={**viewer, **O})).status_code == 403
    assert (await client.post(url, json={}, headers={**owner, **O})).status_code == 422
    assert (await client.post(url, json={"remove": {"on": True}}, headers={**owner, **O})).status_code == 422
    # B can't edit A's photo, nor use A's photo as a reference
    b_photo = (await upload(client, tenants["b"], owner_b, jpeg(1200, 1200))).json()
    cross = {"swap": {"on": True, "reference_asset_id": photo["asset_id"]}}
    assert (await client.post(media_url(tenants["b"], f"/{b_photo['asset_id']}/edits"), json=cross, headers={**owner_b, **O})).status_code == 404
    assert (await client.post(media_url(tenants["b"], f"/{photo['asset_id']}/edits"), json=remove, headers={**owner_b, **O})).status_code == 404

    fal.fail = True
    r = await client.post(url, json=remove, headers={**owner, **O})
    edited = (await listing(client, tenants["a"], owner))[r.json()["asset_id"]]
    assert edited["status"] == "failed" and "model crashed" in edited["edit"]["error"] and edited["urls"] == {}
    assert (await client.post(media_url(tenants["a"], f"/{edited['asset_id']}/approve"), headers={**owner, **O})).status_code == 409

    from del_social.main import app
    from del_social.routes.media import get_fal

    app.dependency_overrides[get_fal] = lambda: None
    assert (await client.post(url, json=remove, headers={**owner, **O})).status_code == 503
