from copy import deepcopy
from typing import Any


REDACTED = "***REDACTED***"
SENSITIVE_KEY_PARTS = (
    "authorization",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "secret",
    "password",
    "encrypted_api_key",
)
SAFE_KEY_PARTS = ("key_prefix", "keyprefix")


def redact_log_payload(payload: Any) -> Any:
    return _redact(deepcopy(payload))


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: REDACTED if _is_sensitive_key(str(key)) else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item) for item in value)
    if isinstance(value, str):
        lowered = value.lower()
        if "authorization:" in lowered or "bearer " in lowered:
            return REDACTED
    return value


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    if any(part in normalized for part in SAFE_KEY_PARTS):
        return False
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)

