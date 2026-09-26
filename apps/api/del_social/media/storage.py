"""Files on the media volume and the signed public URLs that serve them.

Layout: <media_root>/<tenant_id>/<asset_id>/original   (never served)
                                          /<variant>-<rev>.jpg  (rendered on demand, cached)
Public URLs are signed (HMAC-SHA256 over tenant, asset, variant, expiry) because
Instagram and Facebook fetch post images without any login. A URL can't be altered to
reach another file, another tenant or another variant, and it stops working when it expires.
"""
import hashlib
import hmac
import os
import shutil
import time
import uuid
from pathlib import Path

URL_TTL = 24 * 3600  # long enough for a scheduled publish and Meta's fetch


class MediaNotConfigured(RuntimeError):
    pass


def _signing_key(secret_key: str) -> bytes:
    if not secret_key:
        raise MediaNotConfigured("SECRET_KEY is not set")
    return hmac.new(secret_key.encode(), b"del-social/media-url/v1", hashlib.sha256).digest()


def sign(secret_key: str, tenant_id: uuid.UUID, asset_id: uuid.UUID, variant: str, expires: int) -> str:
    msg = f"{tenant_id}/{asset_id}/{variant}/{expires}".encode()
    return hmac.new(_signing_key(secret_key), msg, hashlib.sha256).hexdigest()[:32]


def verify(secret_key: str, tenant_id: uuid.UUID, asset_id: uuid.UUID, variant: str, expires: int, sig: str) -> bool:
    if expires < time.time():
        return False
    return hmac.compare_digest(sign(secret_key, tenant_id, asset_id, variant, expires), sig)


def signed_url(
    base_url: str, secret_key: str, tenant_id: uuid.UUID, asset_id: uuid.UUID, variant: str, ttl: int = URL_TTL
) -> str:
    # Round the expiry to the hour so the same URL is reused (browser and CDN caching)
    expires = (int(time.time()) // 3600 + 1) * 3600 + ttl
    sig = sign(secret_key, tenant_id, asset_id, variant, expires)
    return f"{base_url.rstrip('/')}/media/{tenant_id}/{asset_id}/{variant}.jpg?exp={expires}&sig={sig}"


class MediaStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)

    def _dir(self, tenant_id: uuid.UUID, asset_id: uuid.UUID) -> Path:
        return self.root / str(tenant_id) / str(asset_id)

    def _atomic_write(self, path: Path, data: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def save_original(self, tenant_id: uuid.UUID, asset_id: uuid.UUID, data: bytes) -> None:
        self._atomic_write(self._dir(tenant_id, asset_id) / "original", data)

    def read_original(self, tenant_id: uuid.UUID, asset_id: uuid.UUID) -> bytes:
        return (self._dir(tenant_id, asset_id) / "original").read_bytes()

    def variant_path(self, tenant_id: uuid.UUID, asset_id: uuid.UUID, variant: str, rev: str) -> Path:
        return self._dir(tenant_id, asset_id) / f"{variant}-{rev}.jpg"

    def save_variant(self, path: Path, data: bytes) -> None:
        self._atomic_write(path, data)

    def delete(self, tenant_id: uuid.UUID, asset_id: uuid.UUID) -> None:
        shutil.rmtree(self._dir(tenant_id, asset_id), ignore_errors=True)
