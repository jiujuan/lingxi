from base64 import urlsafe_b64decode, urlsafe_b64encode
import hashlib
import hmac
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from server.app.core.config import settings

# Current format: AES-256-GCM authenticated encryption.
#   enc:v2:<b64url nonce>:<b64url ciphertext+tag>
# Legacy format (still decryptable for smooth migration):
#   enc:v1:<b64url salt>:<b64url ciphertext>:<b64url hmac>
SECRET_PREFIX_V2 = "enc:v2"
SECRET_PREFIX_V1 = "enc:v1"
_NONCE_BYTES = 12


def _derive_key(secret_key: str) -> bytes:
    """32-byte key for AES-256-GCM, derived from the configured secret string."""
    return hashlib.sha256(secret_key.encode("utf-8")).digest()


def _b64encode(value: bytes) -> str:
    return urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return urlsafe_b64decode(value + padding)


def encrypt_secret(plaintext: str | None, *, secret_key: str | None = None) -> str | None:
    if plaintext is None or plaintext == "":
        return None
    key = _derive_key(secret_key or settings.secret_encryption_key)
    nonce = os.urandom(_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)
    return f"{SECRET_PREFIX_V2}:{_b64encode(nonce)}:{_b64encode(ciphertext)}"


def decrypt_secret(encrypted: str | None, *, secret_key: str | None = None) -> str | None:
    if not encrypted:
        return None

    key_str = secret_key or settings.secret_encryption_key
    parts = encrypted.split(":")
    prefix = ":".join(parts[:2])

    if prefix == SECRET_PREFIX_V2:
        if len(parts) != 4:
            raise ValueError("Secret envelope is invalid")
        nonce = _b64decode(parts[2])
        ciphertext = _b64decode(parts[3])
        try:
            plaintext = AESGCM(_derive_key(key_str)).decrypt(nonce, ciphertext, None)
        except InvalidTag as exc:
            raise ValueError("Secret envelope signature is invalid") from exc
        return plaintext.decode("utf-8")

    if prefix == SECRET_PREFIX_V1:
        return _decrypt_legacy_v1(parts, key_str)

    raise ValueError("Secret envelope is invalid")


def _decrypt_legacy_v1(parts: list[str], secret_key: str) -> str:
    """Decrypt the pre-AEAD custom envelope so existing rows keep working.

    Retained only for reading data written before the AES-GCM migration; new
    secrets are always written as enc:v2. Re-encrypt with scripts/reencrypt_secrets.py.
    """
    if len(parts) != 5:
        raise ValueError("Secret envelope is invalid")
    key = hashlib.sha256(secret_key.encode("utf-8")).digest()
    salt = _b64decode(parts[2])
    ciphertext = _b64decode(parts[3])
    signature = _b64decode(parts[4])
    expected = hmac.new(key, salt + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Secret envelope signature is invalid")
    stream = _legacy_keystream(key, salt, len(ciphertext))
    plaintext = bytes(item ^ stream[index] for index, item in enumerate(ciphertext))
    return plaintext.decode("utf-8")


def _legacy_keystream(key: bytes, salt: bytes, length: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < length:
        block = hashlib.sha256(key + salt + counter.to_bytes(4, "big")).digest()
        output.extend(block)
        counter += 1
    return bytes(output[:length])


def has_secret(encrypted: str | None) -> bool:
    return bool(encrypted)
