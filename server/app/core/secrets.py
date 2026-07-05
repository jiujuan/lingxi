from base64 import urlsafe_b64decode, urlsafe_b64encode
import hashlib
import hmac
import os

from server.app.core.config import settings

SECRET_PREFIX = "enc:v1"


def _key_material() -> bytes:
    return hashlib.sha256(settings.secret_encryption_key.encode("utf-8")).digest()


def _b64encode(value: bytes) -> str:
    return urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return urlsafe_b64decode(value + padding)


def _keystream(key: bytes, salt: bytes, length: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < length:
        block = hashlib.sha256(key + salt + counter.to_bytes(4, "big")).digest()
        output.extend(block)
        counter += 1
    return bytes(output[:length])


def encrypt_secret(plaintext: str | None) -> str | None:
    if plaintext is None:
        return None
    if plaintext == "":
        return None

    key = _key_material()
    salt = os.urandom(16)
    data = plaintext.encode("utf-8")
    stream = _keystream(key, salt, len(data))
    ciphertext = bytes(item ^ stream[index] for index, item in enumerate(data))
    signature = hmac.new(key, salt + ciphertext, hashlib.sha256).digest()
    return f"{SECRET_PREFIX}:{_b64encode(salt)}:{_b64encode(ciphertext)}:{_b64encode(signature)}"


def decrypt_secret(encrypted: str | None) -> str | None:
    if not encrypted:
        return None

    parts = encrypted.split(":")
    if len(parts) != 5 or ":".join(parts[:2]) != SECRET_PREFIX:
        raise ValueError("Secret envelope is invalid")

    key = _key_material()
    salt = _b64decode(parts[2])
    ciphertext = _b64decode(parts[3])
    signature = _b64decode(parts[4])
    expected = hmac.new(key, salt + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Secret envelope signature is invalid")

    stream = _keystream(key, salt, len(ciphertext))
    plaintext = bytes(item ^ stream[index] for index, item in enumerate(ciphertext))
    return plaintext.decode("utf-8")


def has_secret(encrypted: str | None) -> bool:
    return bool(encrypted)
