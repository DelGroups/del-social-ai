"""Publishing to Instagram and Facebook through the Graph API (docs/phase-1-plan.md step 7).

Instagram: one media container per photo → wait until FINISHED → (carousel container) →
media_publish. Facebook: one photo post, or unpublished photos attached to one feed post.
Images are fetched by Meta from our signed public URLs. Nothing here decides *what* to
publish; the caller passes the approved caption and photos.
"""
import asyncio
import json
import time

from del_social.connections.meta import MetaClient, MetaError

MAX_PHOTOS = 10


async def _wait_ready(meta: MetaClient, container_id: str, token: str, poll: float, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while True:
        status = (await meta.api(container_id, token, fields="status_code,status")).get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise MetaError(f"Instagram could not process the image ({status})")
        if time.monotonic() > deadline:
            raise MetaError("Instagram took too long to process the image")
        await asyncio.sleep(poll)


async def publish_instagram(
    meta: MetaClient, ig_user_id: str, token: str, image_urls: list[str], caption: str,
    poll: float = 2.0, timeout: float = 120.0,
) -> dict[str, str]:
    if not 1 <= len(image_urls) <= MAX_PHOTOS:
        raise MetaError(f"Instagram posts take 1 to {MAX_PHOTOS} photos")
    if len(image_urls) == 1:
        container = (await meta.post(f"{ig_user_id}/media", token, image_url=image_urls[0], caption=caption))["id"]
    else:
        children = []
        for url in image_urls:
            child = (await meta.post(f"{ig_user_id}/media", token, image_url=url, is_carousel_item="true"))["id"]
            await _wait_ready(meta, child, token, poll, timeout)
            children.append(child)
        container = (await meta.post(
            f"{ig_user_id}/media", token, media_type="CAROUSEL", children=",".join(children), caption=caption
        ))["id"]
    await _wait_ready(meta, container, token, poll, timeout)
    media_id = (await meta.post(f"{ig_user_id}/media_publish", token, creation_id=container))["id"]
    try:
        url = (await meta.api(media_id, token, fields="permalink")).get("permalink", "")
    except MetaError:
        url = ""  # published; the link is only a convenience
    return {"id": media_id, "url": url}


async def publish_facebook(meta: MetaClient, page_id: str, token: str, image_urls: list[str], caption: str) -> dict[str, str]:
    if not 1 <= len(image_urls) <= MAX_PHOTOS:
        raise MetaError(f"Facebook posts here take 1 to {MAX_PHOTOS} photos")
    if len(image_urls) == 1:
        r = await meta.post(f"{page_id}/photos", token, url=image_urls[0], message=caption, published="true")
        post_id = r.get("post_id") or r["id"]
    else:
        ids = [(await meta.post(f"{page_id}/photos", token, url=u, published="false"))["id"] for u in image_urls]
        r = await meta.post(
            f"{page_id}/feed", token, message=caption, attached_media=json.dumps([{"media_fbid": i} for i in ids])
        )
        post_id = r["id"]
    return {"id": post_id, "url": f"https://www.facebook.com/{post_id}"}


PAGE_FIELDS = ("about", "description", "website", "phone", "emails")


async def update_page_profile(meta: MetaClient, page_id: str, token: str, fields: dict[str, str]) -> None:
    """Facebook page details. (Instagram bio and both profile pictures cannot be set via the API.)"""
    data = {k: v for k, v in fields.items() if k in PAGE_FIELDS and v is not None}
    if "emails" in data:
        data["emails"] = json.dumps([e.strip() for e in data["emails"].split(",") if e.strip()])
    if data:
        await meta.post(page_id, token, **data)
