"""Password hashing and tokens. Pure functions: no database needed."""
import pytest
from argon2 import PasswordHasher

from del_social.core.security import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    PasswordPolicyError,
    hash_password,
    hash_token,
    needs_rehash,
    new_token,
    validate_password,
    verify_password,
)

GOOD = "correct horse battery"


def test_hash_and_verify():
    h = hash_password(GOOD)
    assert h.startswith("$argon2id$")
    assert GOOD not in h
    assert verify_password(GOOD, h)
    assert not verify_password(GOOD + "x", h)


def test_same_password_hashes_differently():
    assert hash_password(GOOD) != hash_password(GOOD)


def test_verify_rejects_garbage_hash():
    assert not verify_password(GOOD, "not-a-real-hash")


def test_verify_rejects_overlong_password_without_hashing():
    h = hash_password(GOOD)
    assert not verify_password("x" * (PASSWORD_MAX_LENGTH + 1), h)


@pytest.mark.parametrize(
    "password", ["x" * (PASSWORD_MIN_LENGTH - 1), "x" * (PASSWORD_MAX_LENGTH + 1)]
)
def test_policy_rejects_length(password):
    with pytest.raises(PasswordPolicyError):
        validate_password(password)


@pytest.mark.parametrize("password", ["alllowercase", "ƏşğıçöüƏşğı", "x" * PASSWORD_MAX_LENGTH])
def test_policy_accepts_length_only(password):
    # No composition rules; Azerbaijani letters count as characters
    validate_password(password)


def test_rehash_needed_for_weaker_parameters():
    weak = PasswordHasher(time_cost=1, memory_cost=1024, parallelism=1).hash(GOOD)
    assert needs_rehash(weak)
    assert not needs_rehash(hash_password(GOOD))


def test_tokens_are_unique_and_hashed():
    t1, h1 = new_token()
    t2, h2 = new_token()
    assert t1 != t2 and h1 != h2
    assert len(h1) == 32
    assert hash_token(t1) == h1
    assert len(t1) >= 43  # 32 random bytes, URL-safe base64
