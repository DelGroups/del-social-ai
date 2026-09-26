"""Encrypts channel tokens at rest (ADR 003). Nothing here touches the database.

AES-256-GCM with a random 96-bit nonce per value. Stored layout:
    1 byte key version | 12 bytes nonce | ciphertext + 16 byte tag
Associated data binds a value to where it is stored (tenant + connection), so a
ciphertext copied into another tenant's row fails to decrypt instead of leaking.
"""
import base64
import binascii
import os
import uuid

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_VERSION = 1
NONCE_BYTES = 12


class VaultError(Exception):
    """Misconfigured key, or a value that is corrupt, tampered with or bound elsewhere."""


def parse_key(value: str) -> bytes:
    """32-byte key from hex (openssl rand -hex 32) or base64 (openssl rand -base64 32)."""
    value = value.strip()
    try:
        key = bytes.fromhex(value) if len(value) == 64 else base64.b64decode(
            value.replace("-", "+").replace("_", "/"), validate=True
        )
    except (ValueError, binascii.Error):
        raise VaultError("TOKEN_VAULT_KEY is not valid hex or base64") from None
    if len(key) != 32:
        raise VaultError("TOKEN_VAULT_KEY must be 32 bytes")
    return key


class TokenVault:
    def __init__(self, key: bytes, version: int = KEY_VERSION):
        if len(key) != 32:
            raise VaultError("Vault key must be 32 bytes")
        self._aead = AESGCM(key)
        self._version = version

    def __repr__(self) -> str:  # never show the key in logs or tracebacks
        return f"TokenVault(version={self._version})"

    def encrypt(self, plaintext: str, *, aad: bytes) -> bytes:
        nonce = os.urandom(NONCE_BYTES)
        return bytes([self._version]) + nonce + self._aead.encrypt(nonce, plaintext.encode(), aad)

    def decrypt(self, blob: bytes, *, aad: bytes) -> str:
        if len(blob) < 1 + NONCE_BYTES + 16 or blob[0] != self._version:
            raise VaultError("Unknown or corrupt vault value")
        nonce, ciphertext = blob[1 : 1 + NONCE_BYTES], blob[1 + NONCE_BYTES :]
        try:
            return self._aead.decrypt(nonce, ciphertext, aad).decode()
        except InvalidTag:
            raise VaultError("Vault value failed authentication") from None


def connection_aad(tenant_id: uuid.UUID, connection_id: uuid.UUID) -> bytes:
    return f"del-social/connection/{tenant_id}/{connection_id}".encode()
