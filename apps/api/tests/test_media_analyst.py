"""Photo Analyst: vision call, what code applies (and never overwrites), product grouping.

The LLM is a scripted fake: no real calls, no cost.
"""
import io
import uuid
from decimal import Decimal

import pytest
from PIL import Image

from del_social.agents.media_analyst import PhotoAnalysis
from del_social.llm import LLMError, LLMResult
from del_social.llm.pricing import Usage

from .conftest import O
from .test_media import jpeg, upload


def analysis(**over) -> PhotoAnalysis:
    base = dict(
        is_furniture=True, looks_like="render", title_az="Ağ qulpsuz qarderob",
        description_az="Yataq otağında tavana qədər ağ qulpsuz qarderob.",
        description_en="A white handleless floor-to-ceiling wardrobe in a bedroom.",
        category="Qarderob", room="yataq otağı", style=["müasir"], colors=["ağ"], materials_visible=[],
        features=["qulpsuz qapılar"], tags=["qarderob", "ağ", "yataq otağı"],
        hashtags=["#DelFurniture", "#qarderob", "#шкафкупе"], focal_x=0.62, focal_y=0.45,
        best_format="landscape", quality_issues=["reflections"], suggested_edits=["reduce reflections on the doors"],
        product_match=None, product_match_confidence=0.0,
    )
    return PhotoAnalysis(**{**base, **over})


class FakeAnalyst:
    def __init__(self):
        self.script: list[PhotoAnalysis | Exception] = []
        self.calls: list[dict] = []

    async def structured(self, *, tenant_id, prompt, user, output, tier, max_tokens, effort=None, images=None):
        self.calls.append({"user": user, "images": images or [], "agent": prompt.agent})
        nxt = self.script.pop(0) if self.script else analysis()
        if isinstance(nxt, Exception):
            raise nxt
        if callable(nxt):
            nxt = nxt(user)
        return LLMResult(nxt, "claude-sonnet-5", Usage(1500, 400), Decimal("0.0070"), 900, uuid.uuid4().hex)


@pytest.fixture
def analyst(client):
    from del_social.main import app
    from del_social.routes.media import get_analyst

    fake = FakeAnalyst()
    app.dependency_overrides[get_analyst] = lambda: fake
    return fake


def murl(tenant_id, path=""):
    return f"/tenants/{tenant_id}/media{path}"


async def listing(client, tenant_id, headers) -> dict[str, dict]:
    return {m["asset_id"]: m for m in (await client.get(murl(tenant_id), headers=headers)).json()}


async def test_upload_is_analysed_and_grouped(client, analyst, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    first = (await upload(client, tenants["a"], owner, jpeg(1920, 1080), description="Wendy modeli")).json()
    assert first["analysis"]["status"] == "queued"
    call = analyst.calls[0]
    assert call["agent"] == "media_analyst" and len(call["images"]) == 1  # no products yet: just the photo
    assert "Wendy modeli" in call["user"] and "<human_notes>" in call["user"]
    Image.open(io.BytesIO(call["images"][0])).verify()  # a real JPEG went to the model

    a = (await listing(client, tenants["a"], owner))[first["asset_id"]]
    assert a["analysis"]["status"] == "done" and a["analysis"]["product_action"] == "created"
    assert a["description"] == "Wendy modeli"  # the human's text is never overwritten
    assert set(a["tags"]) >= {"qarderob", "ağ", "yataq otağı"}
    assert (a["focal_x"], a["focal_y"]) == (0.62, 0.45)
    assert a["analysis"]["best_format"] == "landscape" and "#шкафкупе" in a["analysis"]["hashtags"]
    products = (await client.get(f"/tenants/{tenants['a']}/products", headers=owner)).json()
    assert [p["name"] for p in products] == ["Ağ qulpsuz qarderob"] and a["product_id"] == products[0]["product_id"]

    # Second angle of the same product: the analyst sees the existing product's cover and matches it
    analyst.script.append(lambda user: analysis(product_match=products[0]["product_id"], product_match_confidence=0.9))
    second = (await upload(client, tenants["a"], owner, jpeg(1920, 1080, color=(200, 200, 200)))).json()
    assert len(analyst.calls[1]["images"]) == 2 and products[0]["product_id"] in analyst.calls[1]["user"]
    b = (await listing(client, tenants["a"], owner))[second["asset_id"]]
    assert b["product_id"] == products[0]["product_id"] and b["position"] == 1
    assert b["analysis"]["product_action"] == "joined"
    assert b["description"] == "Yataq otağında tavana qədər ağ qulpsuz qarderob."  # empty → filled

    # A doubtful match does not join: a new product is made instead
    analyst.script.append(analysis(title_az="Boz künc divanı", product_match=products[0]["product_id"], product_match_confidence=0.4))
    third = (await upload(client, tenants["a"], owner, jpeg(1600, 1600, color=(90, 90, 90)))).json()
    c = (await listing(client, tenants["a"], owner))[third["asset_id"]]
    assert c["product_id"] != products[0]["product_id"] and c["analysis"]["product_action"] == "created"


async def test_manual_choices_are_kept(client, analyst, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    p = (await client.post(f"/tenants/{tenants['a']}/products", json={"name": "Wendy"}, headers={**owner, **O})).json()
    photo = (await upload(client, tenants["a"], owner, jpeg(1600, 1200), product_id=p["product_id"])).json()
    a = (await listing(client, tenants["a"], owner))[photo["asset_id"]]
    assert a["product_id"] == p["product_id"] and a["analysis"]["product_action"] is None


async def test_not_furniture_is_not_grouped(client, analyst, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    analyst.script.append(analysis(is_furniture=False))
    photo = (await upload(client, tenants["a"], owner, jpeg(1200, 1200))).json()
    assert (await listing(client, tenants["a"], owner))[photo["asset_id"]]["product_id"] is None


async def test_analyse_all_and_failures(client, tenants, session_for):
    from del_social.main import app
    from del_social.routes.media import get_analyst

    owner = await session_for(tenants["a_owner"])
    viewer = await session_for(tenants["a_viewer"])
    app.dependency_overrides[get_analyst] = lambda: None
    old = [(await upload(client, tenants["a"], owner, jpeg(1200, 1200, color=(i * 40, 0, 0)))).json() for i in range(1, 3)]
    assert all(m["analysis"] is None for m in old)
    assert (await client.post(murl(tenants["a"], "/analyze-all"), headers={**owner, **O})).status_code == 503

    fake = FakeAnalyst()
    fake.script = [LLMError("Anthropic API error 400 (credit balance too low)"), analysis()]
    app.dependency_overrides[get_analyst] = lambda: fake
    assert (await client.post(murl(tenants["a"], "/analyze-all"), headers={**viewer, **O})).status_code == 403
    r = await client.post(murl(tenants["a"], "/analyze-all"), headers={**owner, **O})
    assert r.json() == {"queued": 2}
    rows = await listing(client, tenants["a"], owner)
    statuses = sorted(rows[m["asset_id"]]["analysis"]["status"] for m in old)
    assert statuses == ["done", "failed"]
    failed = next(rows[m["asset_id"]] for m in old if rows[m["asset_id"]]["analysis"]["status"] == "failed")
    assert "credit" in failed["analysis"]["error"]

    retry = await client.post(murl(tenants["a"], f"/{failed['asset_id']}/analyze"), headers={**owner, **O})
    assert retry.status_code == 202
    assert (await listing(client, tenants["a"], owner))[failed["asset_id"]]["analysis"]["status"] == "done"
    assert (await client.post(murl(tenants["a"], "/analyze-all"), headers={**owner, **O})).json() == {"queued": 0}
