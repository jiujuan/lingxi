import hashlib
import hmac
from base64 import urlsafe_b64encode

import pytest

from server.app.core.secrets import (
    SECRET_PREFIX_V2,
    decrypt_secret,
    encrypt_secret,
)


def _b64(value: bytes) -> str:
    return urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _legacy_v1_encrypt(plaintext: str, secret_key: str) -> str:
    """Reproduce the pre-AEAD enc:v1 envelope, for backward-compat testing."""
    key = hashlib.sha256(secret_key.encode("utf-8")).digest()
    salt = b"0123456789abcdef"
    data = plaintext.encode("utf-8")

    output = bytearray()
    counter = 0
    while len(output) < len(data):
        output.extend(hashlib.sha256(key + salt + counter.to_bytes(4, "big")).digest())
        counter += 1
    stream = bytes(output[: len(data)])

    ciphertext = bytes(b ^ stream[i] for i, b in enumerate(data))
    signature = hmac.new(key, salt + ciphertext, hashlib.sha256).digest()
    return f"enc:v1:{_b64(salt)}:{_b64(ciphertext)}:{_b64(signature)}"


def test_encrypt_roundtrip_uses_aes_gcm_v2():
    token = encrypt_secret("sk-super-secret")
    assert token is not None
    assert token.startswith(SECRET_PREFIX_V2)
    assert "sk-super-secret" not in token  # not stored in cleartext
    assert decrypt_secret(token) == "sk-super-secret"


def test_encrypt_empty_and_none_return_none():
    assert encrypt_secret(None) is None
    assert encrypt_secret("") is None
    assert decrypt_secret(None) is None
    assert decrypt_secret("") is None


def test_nonce_is_random_so_ciphertext_differs():
    assert encrypt_secret("same") != encrypt_secret("same")


def test_tampered_ciphertext_is_rejected():
    token = encrypt_secret("sk-secret")
    prefix, nonce, ciphertext = token.rsplit(":", 2)
    flipped = "A" if ciphertext[0] != "A" else "B"
    tampered = f"{prefix}:{nonce}:{flipped}{ciphertext[1:]}"
    with pytest.raises(ValueError):
        decrypt_secret(tampered)


def test_legacy_v1_envelope_still_decrypts():
    from server.app.core.config import settings

    legacy = _legacy_v1_encrypt("sk-legacy", settings.secret_encryption_key)
    assert legacy.startswith("enc:v1")
    assert decrypt_secret(legacy) == "sk-legacy"


def test_key_rotation_via_secret_key_param():
    # encrypted under the old key ...
    token = encrypt_secret("sk-rotate", secret_key="old-key-value")
    # ... cannot be read with the new key ...
    with pytest.raises(ValueError):
        decrypt_secret(token, secret_key="new-key-value")
    # ... but re-encrypting (decrypt old -> encrypt new) migrates it
    plaintext = decrypt_secret(token, secret_key="old-key-value")
    rotated = encrypt_secret(plaintext, secret_key="new-key-value")
    assert decrypt_secret(rotated, secret_key="new-key-value") == "sk-rotate"
