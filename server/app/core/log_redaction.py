from copy import deepcopy
import re
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

# Value-level fallback: secret-looking tokens that may appear under otherwise
# innocuous keys (e.g. a message body that quotes a key). Matched substrings are
# replaced so surrounding context is preserved. Kept specific to avoid nuking
# request ids / ordinary text.
_SECRET_VALUE_RE = re.compile(
    r"(?:"
    r"eyJ[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}"  # JWT
    r"|lk_(?:live|test)_[A-Za-z0-9_-]{8,}"  # API key
    r"|sk-[A-Za-z0-9]{16,}"  # OpenAI-style key
    r"|enc:v\d+:[A-Za-z0-9_:+/=-]{8,}"  # secret envelope
    r")"
)


def redact_log_payload(payload: Any) -> Any:
    return _redact(deepcopy(payload))


def _redact(value: Any, safe: bool = False) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if _is_sensitive_key(str(key)):
                result[key] = REDACTED
            else:
                result[key] = _redact(item, safe=safe or _is_safe_key(str(key)))
        return result
    if isinstance(value, list):
        return [_redact(item, safe=safe) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact(item, safe=safe) for item in value)
    if isinstance(value, str):
        return value if safe else _redact_string(value)
    return value


def _redact_string(value: str) -> str:
    lowered = value.lower()
    if "authorization:" in lowered or "bearer " in lowered:
        return REDACTED
    return _SECRET_VALUE_RE.sub(REDACTED, value)


def _is_sensitive_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    if any(part in normalized for part in SAFE_KEY_PARTS):
        return False
    return any(part in normalized for part in SENSITIVE_KEY_PARTS)


def _is_safe_key(key: str) -> bool:
    normalized = key.replace("-", "_").lower()
    return any(part in normalized for part in SAFE_KEY_PARTS)
