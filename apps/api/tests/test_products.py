"""Products: several photos of one product, their order, the post logo, the landscape format."""
import io

from PIL import Image

from .conftest import O
from .test_image_editing import fal  # noqa: F401  (fixture)
from .test_media import jpeg, logo_png, opened, path_of, upload


def purl(tenant_id, path=""):
    return f"/tenants/{tenant_id}/products{path}"


def murl(tenant_id, path=""):
    return f"/tenants/{tenant_id}/media{path}"


def solid_png(color) -> bytes:
    out = io.BytesIO()
    Image.new("RGBA", (400, 200), color).save(out, "PNG")
    return out.getvalue()


async def test_product_groups_ordered_photos(client, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    p = (await client.post(purl(tenants["a"]), json={"name": " Wendy qarderob ", "category": "Qarderob"}, headers={**owner, **O})).json()
    assert p["name"] == "Wendy qarderob" and p["photos"] == 0

    ids = []
    for color in ((200, 0, 0), (0, 200, 0), (0, 0, 200)):
        r = await upload(client, tenants["a"], owner, jpeg(1920, 1080, color=color), product_id=p["product_id"])
        assert r.status_code == 201, r.text
        ids.append(r.json()["asset_id"])
    photos = (await client.get(murl(tenants["a"], f"?product_id={p['product_id']}"), headers=owner)).json()
    assert [m["asset_id"] for m in photos] == ids and [m["position"] for m in photos] == [0, 1, 2]
    assert (await client.get(purl(tenants["a"]), headers=owner)).json()[0]["photos"] == 3

    new_order = [ids[2], ids[0], ids[1]]
    assert (await client.put(purl(tenants["a"], f"/{p['product_id']}/order"), json={"asset_ids": new_order}, headers={**owner, **O})).status_code == 200
    photos = (await client.get(murl(tenants["a"], f"?product_id={p['product_id']}"), headers=owner)).json()
    assert [m["asset_id"] for m in photos] == new_order
    bad = await client.put(purl(tenants["a"], f"/{p['product_id']}/order"), json={"asset_ids": new_order[:2]}, headers={**owner, **O})
    assert bad.status_code == 409

    # Move a photo out of the product, and a loose photo into it (goes last)
    await client.patch(murl(tenants["a"], f"/{ids[0]}"), json={"product_id": None}, headers={**owner, **O})
    loose = (await upload(client, tenants["a"], owner, jpeg(1200, 1200))).json()
    moved = await client.patch(murl(tenants["a"], f"/{loose['asset_id']}"), json={"product_id": p["product_id"]}, headers={**owner, **O})
    assert moved.json()["product_id"] == p["product_id"] and moved.json()["position"] == 3

    renamed = await client.patch(purl(tenants["a"], f"/{p['product_id']}"), json={"name": "Wendy"}, headers={**owner, **O})
    assert renamed.json()["name"] == "Wendy" and renamed.json()["photos"] == 3

    assert (await client.delete(purl(tenants["a"], f"/{p['product_id']}"), headers={**owner, **O})).status_code == 204
    assert (await client.get(purl(tenants["a"]), headers=owner)).json() == []
    everything = (await client.get(murl(tenants["a"]), headers=owner)).json()
    assert len(everything) == 4 and all(m["product_id"] is None for m in everything)  # photos kept


async def test_products_roles_and_isolation(client, tenants, session_for):
    owner_a = await session_for(tenants["a_owner"])
    viewer_a = await session_for(tenants["a_viewer"])
    owner_b = await session_for(tenants["b_owner"])
    assert (await client.post(purl(tenants["a"]), json={"name": "X"}, headers={**viewer_a, **O})).status_code == 403
    p = (await client.post(purl(tenants["a"]), json={"name": "X"}, headers={**owner_a, **O})).json()
    assert (await client.get(purl(tenants["a"]), headers=viewer_a)).status_code == 200
    assert (await client.get(purl(tenants["b"]), headers=owner_b)).json() == []
    # B can't put its photo into A's product, or rename it
    r = await upload(client, tenants["b"], owner_b, jpeg(1000, 1000), product_id=p["product_id"])
    assert r.status_code == 404
    assert (await client.patch(purl(tenants["b"], f"/{p['product_id']}"), json={"name": "Y"}, headers={**owner_b, **O})).status_code == 404
    assert (await client.post(purl(tenants["a"]), json={"name": ""}, headers={**owner_a, **O})).status_code == 422
    logo = await upload(client, tenants["a"], owner_a, logo_png(), kind="logo", name="logo.png", product_id=p["product_id"])
    assert logo.status_code == 422


async def test_edit_of_a_product_photo_stays_in_the_product(client, fal, tenants, session_for):  # noqa: F811
    owner = await session_for(tenants["a_owner"])
    p = (await client.post(purl(tenants["a"]), json={"name": "Wendy"}, headers={**owner, **O})).json()
    photo = (await upload(client, tenants["a"], owner, jpeg(1600, 1200), product_id=p["product_id"])).json()
    r = await client.post(murl(tenants["a"], f"/{photo['asset_id']}/edits"), json={"enhance": True}, headers={**owner, **O})
    assert r.json()["product_id"] == p["product_id"] and r.json()["position"] == 1


async def test_post_logo_choice_and_landscape(client, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    green = (await upload(client, tenants["a"], owner, solid_png((0, 200, 0, 255)), kind="logo", name="full.png")).json()
    await upload(client, tenants["a"], owner, solid_png((200, 0, 0, 255)), kind="logo", name="round.png")
    photo = (await upload(client, tenants["a"], owner, jpeg(1920, 1080, color=(250, 250, 250)))).json()

    def corner(data: bytes, size):
        return opened(data).getpixel((size[0] - 60, size[1] - 30))

    red_first = await client.get(path_of(photo["urls"]["landscape-logo"]))
    assert opened(red_first.content).size == (1080, 566)
    assert corner(red_first.content, (1080, 566))[0] > 150  # newest logo (red) by default

    chosen = await client.post(murl(tenants["a"], f"/{green['asset_id']}/default-logo"), headers={**owner, **O})
    assert chosen.status_code == 200 and chosen.json()["default_logo"] is True
    photo = next(m for m in (await client.get(murl(tenants["a"], "?kind=photo"), headers=owner)).json())
    green_now = await client.get(path_of(photo["urls"]["landscape-logo"]))
    assert corner(green_now.content, (1080, 566))[1] > 150  # the chosen (green) logo
    assert (await client.post(murl(tenants["a"], f"/{photo['asset_id']}/default-logo"), headers={**owner, **O})).status_code == 409


async def test_merge_products(client, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    a = (await client.post(purl(tenants["a"]), json={"name": "şkaf wendi modeli"}, headers={**owner, **O})).json()
    b = (await client.post(purl(tenants["a"]), json={"name": "Wendy qarderobu"}, headers={**owner, **O})).json()
    a_ids = [(await upload(client, tenants["a"], owner, jpeg(1200, 1200, color=(i * 50, 0, 0)), product_id=a["product_id"])).json()["asset_id"] for i in (1, 2)]
    b_id = (await upload(client, tenants["a"], owner, jpeg(1200, 1200, color=(0, 0, 150)), product_id=b["product_id"])).json()["asset_id"]
    merged = await client.post(purl(tenants["a"], f"/{a['product_id']}/merge"), json={"into_product_id": b["product_id"]}, headers={**owner, **O})
    assert merged.status_code == 200 and merged.json()["photos"] == 3
    photos = (await client.get(murl(tenants["a"], f"?product_id={b['product_id']}"), headers=owner)).json()
    assert [m["asset_id"] for m in photos] == [b_id, *a_ids] and [m["position"] for m in photos] == [0, 1, 2]
    assert [p["name"] for p in (await client.get(purl(tenants["a"]), headers=owner)).json()] == ["Wendy qarderobu"]
    same = await client.post(purl(tenants["a"], f"/{b['product_id']}/merge"), json={"into_product_id": b["product_id"]}, headers={**owner, **O})
    assert same.status_code == 409
