"""Password hashing and opaque tokens (ADR 002). Nothing here touches the database."""
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# argon2id with the library's defaults (RFC 9106 low-memory profile, per OWASP)
_hasher = PasswordHasher()

PASSWORD_MIN_LENGTH = 10
PASSWORD_MAX_LENGTH = 128  # caps hashing cost per request


class PasswordPolicyError(ValueError):
    pass


def validate_password(password: str) -> None:
    """Length only: composition rules push people to predictable passwords (NIST SP 800-63B)."""
    if len(password) < PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError(f"Password must be at least {PASSWORD_MIN_LENGTH} characters")
    if len(password) > PASSWORD_MAX_LENGTH:
        raise PasswordPolicyError(f"Password must be at most {PASSWORD_MAX_LENGTH} characters")


def hash_password(password: str) -> str:
    validate_password(password)
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    if len(password) > PASSWORD_MAX_LENGTH:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def burn_verify_time(password: str) -> None:
    """Spend the same time as a real check so unknown emails can't be told apart by timing."""
    verify_password(password[:PASSWORD_MAX_LENGTH], _DUMMY_HASH)


def hash_token(token: str) -> bytes:
    """SHA-256 of an opaque token. Tokens have 256 bits of entropy, so no salt or KDF is needed."""
    return hashlib.sha256(token.encode()).digest()


def new_token() -> tuple[str, bytes]:
    """A random URL-safe token for the client and its hash for the database."""
    token = secrets.token_urlsafe(32)
    return token, hash_token(token)
