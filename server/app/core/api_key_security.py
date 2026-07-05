import hashlib
import hmac
import secrets

from server.app.core.config import settings

KEY_PREFIX = "lk_live_"


def generate_api_key() -> tuple[str, str]:
    key = f"{KEY_PREFIX}{secrets.token_urlsafe(24)}"
    return key, key[:16]


def hash_api_key(key: str) -> str:
    return hmac.new(
        settings.secret_encryption_key.encode("utf-8"),
        key.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_api_key(key: str, stored_hash: str) -> bool:
    return hmac.compare_digest(hash_api_key(key), stored_hash)


def api_key_prefix(key: str) -> str:
    return key[:16] if key.startswith(KEY_PREFIX) else ""
