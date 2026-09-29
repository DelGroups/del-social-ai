"""Where lab files live, chunked uploads, and short-lived signed links for the AI models.

<media_root>/<tenant_id>/yt-lab/<media_id>/source.<ext> | video.mp4 | audio.mp3 | subs.ass | frame.jpg
fal.ai fetches audio and images by URL: the link is signed (HMAC, like photo links) and expires in
two hours; nothing else in the folder can be reached with it.
"""
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from del_social.media.storage import sign, verify

MAX_UPLOAD = 4 * 1024**3  # 4 GB per video
MAX_CHUNK = 16 * 1024 * 1024
MAX_TENANT_BYTES = 12 * 1024**3  # lab space per company (the server disk is shared)
LINK_TTL = 2 * 3600
PUBLIC_FILES = ("audio.mp3", "frame.jpg", "video.mp4")
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi"}


class LabError(ValueError):
    """Safe to show."""


def folder(root: str, tenant_id: uuid.UUID, media_id: uuid.UUID) -> Path:
    return Path(root) / str(tenant_id) / "yt-lab" / str(media_id)


def source_name(filename: str) -> str:
    ext = os.path.splitext(filename.lower())[1]
    if ext not in VIDEO_EXT:
        raise LabError("Upload a video file (MP4, MOV, MKV, WEBM)")
    return f"source{ext}"


def clean_title(filename: str) -> str:
    return re.sub(r"[_\-]+", " ", os.path.splitext(os.path.basename(filename))[0]).strip()[:120] or "Video"


def append(path: Path, offset: int, data: bytes) -> int:
    """Write one chunk at `offset` (must be the current size: resumable, never overlapping). Returns the new size."""
    path.parent.mkdir(parents=True, exist_ok=True)
    size = path.stat().st_size if path.exists() else 0
    if offset != size:
        raise LabError(f"Expected the chunk at byte {size}")
    if len(data) > MAX_CHUNK:
        raise LabError("Chunk too large")
    with open(path, "ab") as f:
        f.write(data)
    return size + len(data)


def usage(root: str, tenant_id: uuid.UUID) -> int:
    base = Path(root) / str(tenant_id) / "yt-lab"
    return sum(p.stat().st_size for p in base.rglob("*") if p.is_file()) if base.exists() else 0


def remove(root: str, tenant_id: uuid.UUID, media_id: uuid.UUID) -> None:
    shutil.rmtree(folder(root, tenant_id, media_id), ignore_errors=True)


def video_path(root: str, tenant_id: uuid.UUID, media_id: uuid.UUID) -> Path:
    """The playable file: video.mp4 for results, source.* for uploads."""
    d = folder(root, tenant_id, media_id)
    if (d / "video.mp4").exists():
        return d / "video.mp4"
    found = sorted(d.glob("source.*"))
    if not found:
        raise LabError("The video file is missing (it may have expired)")
    return found[0]


def public_link(base_url: str, secret: str, tenant_id: uuid.UUID, media_id: uuid.UUID, name: str) -> str:
    expires = int(time.time()) + LINK_TTL
    sig = sign(secret, tenant_id, media_id, f"lab/{name}", expires)
    return f"{base_url.rstrip('/')}/lab-files/{tenant_id}/{media_id}/{name}?exp={expires}&sig={sig}"


def check_link(secret: str, tenant_id: uuid.UUID, media_id: uuid.UUID, name: str, exp: int, sig: str) -> bool:
    return name in PUBLIC_FILES and verify(secret, tenant_id, media_id, f"lab/{name}", exp, sig)
