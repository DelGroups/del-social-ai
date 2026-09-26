"""Media library: image checks and preparation, signed URLs, upload/list/frame/delete, isolation."""
import io
import time
import uuid

import pytest
from PIL import Image

from del_social.media import images
from del_social.media.storage import sign, signed_url, verify

from .conftest import O

SECRET = "test-secret-key"


def jpeg(w: int, h: int, color=(120, 90, 60), orientation: int | None = None) -> bytes:
    img = Image.new("RGB", (w, h), color)
    out = io.BytesIO()
    exif = Image.Exif()
    exif[0x0112] = orientation or 1
    exif[0x8825] = {2: (40.0, 22.0, 0.0)}  # a GPS block, which must never be published
    img.save(out, "JPEG", exif=exif.tobytes())
    return out.getvalue()


def halves(w: int, h: int) -> bytes:
    """Left half red, right half blue."""
    img = Image.new("RGB", (w, h), (220, 20, 20))
    img.paste((20, 20, 220), (w // 2, 0, w, h))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def logo_png() -> bytes:
    img = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    img.paste((0, 200, 0, 255), (0, 0, 400, 200))
    out = io.BytesIO()
    img.save(out, "PNG")
    return out.getvalue()


def opened(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))


# --- image checks and preparation ---


def test_inspect_accepts_real_images_and_applies_orientation():
    info = images.inspect(jpeg(2000, 1000, orientation=6))  # camera held upright
    assert (info.format, info.width, info.height) == ("JPEG", 1000, 2000)
    assert images.inspect(logo_png(), images.MIN_LOGO_SIDE).has_alpha


@pytest.mark.parametrize("data, reason", [
    (b"not an image at all", "not a readable image"),
    (jpeg(200, 200), "too small"),
])
def test_inspect_rejects(data, reason):
    with pytest.raises(images.ImageRejected, match=reason):
        images.inspect(data)


def test_inspect_rejects_other_formats():
    out = io.BytesIO()
    Image.new("RGB", (800, 800)).save(out, "GIF")
    with pytest.raises(images.ImageRejected, match="JPEG, PNG"):
        images.inspect(out.getvalue())


def test_render_sizes_and_strips_metadata():
    feed = opened(images.render(jpeg(3000, 2000), "feed"))
    assert feed.size == (1080, 1350) and feed.format == "JPEG"
    assert not feed.getexif()  # no GPS or camera data leaves the server
    assert opened(images.render(jpeg(3000, 2000), "square")).size == (1080, 1080)
    thumb = opened(images.render(jpeg(3000, 2000), "thumb"))
    assert max(thumb.size) == 480 and thumb.size[0] / thumb.size[1] == pytest.approx(1.5, abs=0.01)


def test_focal_point_decides_the_crop():
    left = opened(images.render(halves(2000, 1000), "feed", focal=(0.0, 0.5), enhance=False)).getpixel((540, 675))
    right = opened(images.render(halves(2000, 1000), "feed", focal=(1.0, 0.5), enhance=False)).getpixel((540, 675))
    assert left[0] > 150 and left[2] < 100  # red side
    assert right[2] > 150 and right[0] < 100  # blue side


def test_enhance_changes_tone_not_colour():
    # A dull, warm, low-contrast photo: a gradient from (80,65,50) to (160,135,110)
    flat = Image.new("RGB", (1200, 1200))
    for x in range(1200):
        f = x / 1199
        flat.paste((round(80 + 80 * f), round(65 + 70 * f), round(50 + 60 * f)), (x, 0, x + 1, 1200))
    buf = io.BytesIO()
    flat.save(buf, "PNG")
    before = opened(images.render(buf.getvalue(), "square", enhance=False))
    after = opened(images.render(buf.getvalue(), "square", enhance=True))

    def span(img):
        return img.getpixel((1070, 540))[0] - img.getpixel((10, 540))[0]

    assert span(after) > span(before) + 20  # more contrast
    for x in (10, 540, 1070):
        r, g, b = after.getpixel((x, 540))
        assert r > g > b  # still warm everywhere: colours kept


def test_logo_goes_bottom_right():
    out = opened(images.render(jpeg(2000, 2000, color=(250, 250, 250)), "square", enhance=False, logo_data=logo_png()))
    corner = out.getpixel((1080 - 60, 1080 - 60))
    top_left = out.getpixel((40, 40))
    assert corner[1] > 150 and corner[0] < 100  # green logo
    assert min(top_left) > 230  # rest of the photo untouched


# --- signed URLs ---


def test_signatures_bind_everything():
    t, a = uuid.uuid4(), uuid.uuid4()
    exp = int(time.time()) + 600
    sig = sign(SECRET, t, a, "feed", exp)
    assert verify(SECRET, t, a, "feed", exp, sig)
    assert not verify(SECRET, t, a, "square", exp, sig)
    assert not verify(SECRET, uuid.uuid4(), a, "feed", exp, sig)
    assert not verify(SECRET, t, a, "feed", exp + 1, sig)
    assert not verify("other-key", t, a, "feed", exp, sig)
    past = int(time.time()) - 1
    assert not verify(SECRET, t, a, "feed", past, sign(SECRET, t, a, "feed", past))
    url = signed_url("https://api.test/", SECRET, t, a, "feed")
    assert url.startswith(f"https://api.test/media/{t}/{a}/feed.jpg?exp=")


# --- API ---


def path_of(url: str) -> str:
    return url.removeprefix("https://api.test")


async def upload(client, tenant_id, headers, data: bytes, kind="photo", name="photo.jpg", **form):
    return await client.post(
        f"/tenants/{tenant_id}/media",
        files={"file": (name, data, "application/octet-stream")},
        data={"kind": kind, **form},
        headers={**headers, **O},
    )


async def test_upload_list_frame_serve_delete(client, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    r = await upload(client, tenants["a"], owner, jpeg(2400, 1600), description="Ağ qarderob", tags="Qarderob, Yataq otağı, qarderob")
    assert r.status_code == 201, r.text
    asset = r.json()
    assert (asset["width"], asset["height"]) == (2400, 1600)
    assert asset["tags"] == ["qarderob", "yataq otağı"]
    assert set(asset["urls"]) == {"thumb", "feed", "square"}

    again = await upload(client, tenants["a"], owner, jpeg(2400, 1600))
    assert again.json()["asset_id"] == asset["asset_id"]  # same file stored once

    listed = (await client.get(f"/tenants/{tenants['a']}/media?tag=qarderob", headers=owner)).json()
    assert [m["asset_id"] for m in listed] == [asset["asset_id"]]

    served = await client.get(path_of(asset["urls"]["feed"]))
    assert served.status_code == 200 and served.headers["content-type"] == "image/jpeg"
    assert opened(served.content).size == (1080, 1350)

    patched = await client.patch(
        f"/tenants/{tenants['a']}/media/{asset['asset_id']}", json={"focal_x": 0.1, "enhance": False},
        headers={**owner, **O},
    )
    assert patched.json()["focal_x"] == 0.1
    assert (await client.get(path_of(patched.json()["urls"]["square"]))).status_code == 200

    feed_url = asset["urls"]["feed"]
    tampered = feed_url.replace("/feed.jpg", "/square.jpg")
    assert (await client.get(path_of(tampered))).status_code == 404

    deleted = await client.delete(f"/tenants/{tenants['a']}/media/{asset['asset_id']}", headers={**owner, **O})
    assert deleted.status_code == 204
    assert (await client.get(path_of(feed_url))).status_code == 404
    assert (await client.get(f"/tenants/{tenants['a']}/media", headers=owner)).json() == []


async def test_logo_variants(client, tenants, session_for):
    owner = await session_for(tenants["a_owner"])
    photo = (await upload(client, tenants["a"], owner, jpeg(2000, 2000, color=(250, 250, 250)))).json()
    assert "feed-logo" not in photo["urls"]
    await upload(client, tenants["a"], owner, logo_png(), kind="logo", name="logo.png")
    photo = next(m for m in (await client.get(f"/tenants/{tenants['a']}/media?kind=photo", headers=owner)).json())
    with_logo = await client.get(path_of(photo["urls"]["square-logo"]))
    assert with_logo.status_code == 200
    corner = opened(with_logo.content).getpixel((1080 - 60, 1080 - 60))
    assert corner[1] > 150 and corner[0] < 100


async def test_roles_validation_and_isolation(client, tenants, session_for):
    owner_a = await session_for(tenants["a_owner"])
    viewer_a = await session_for(tenants["a_viewer"])
    owner_b = await session_for(tenants["b_owner"])
    assert (await upload(client, tenants["a"], viewer_a, jpeg(1000, 1000))).status_code == 403
    bad = await upload(client, tenants["a"], owner_a, b"%PDF-1.4 not an image")
    assert bad.status_code == 422 and "not a readable image" in bad.text
    asset = (await upload(client, tenants["a"], owner_a, jpeg(1000, 1000))).json()
    assert (await client.get(f"/tenants/{tenants['a']}/media", headers=viewer_a)).status_code == 200

    # Tenant B can't see, change or delete A's photo
    assert (await client.get(f"/tenants/{tenants['b']}/media", headers=owner_b)).json() == []
    assert (await client.patch(f"/tenants/{tenants['b']}/media/{asset['asset_id']}", json={"description": "x"}, headers={**owner_b, **O})).status_code == 404
    assert (await client.delete(f"/tenants/{tenants['b']}/media/{asset['asset_id']}", headers={**owner_b, **O})).status_code == 404
    # A valid signature for A's asset doesn't open it under B's tenant id
    moved = path_of(asset["urls"]["feed"]).replace(str(tenants["a"]), str(tenants["b"]))
    assert (await client.get(moved)).status_code == 404
