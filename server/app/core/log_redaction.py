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


_SNAPSHOT_ROOT_FIELDS = {
    "channels",
    "configHash",
    "featureFlags",
    "rrfParameters",
    "chunkRetrievalDegraded",
    "filters",
    "latencyMs",
    "requestId",
}
_SNAPSHOT_ITEM_FIELDS = {
    "qaPairId",
    "documentId",
    "chunkId",
    "parentChunkId",
    "evidenceId",
    "evidenceType",
    "pageNo",
    "pageStart",
    "pageEnd",
    "rank",
    "score",
    "vectorScore",
    "textScore",
    "rrfScore",
    "rerankScore",
    "fusedScore",
    "channelScores",
    "channelRanks",
}
_SNAPSHOT_FILTER_FIELDS = {
    "scopeDocumentIds",
    "scopeSpaceId",
    "scopeClassificationDepartmentId",
    "scopeCategoryId",
}


def sanitize_retrieval_snapshot(
    snapshot: Any, *, max_items_per_stage: int
) -> dict[str, Any]:
    """Return a bounded audit snapshot with only retrieval metadata.

    Retrieval snapshots are often persisted or exported for troubleshooting.
    They must retain ranks, fusion provenance, and configuration while never
    retaining user query text, document text, quotes, titles, or embeddings.
    """

    if not isinstance(snapshot, dict):
        return {}
    cap = max(0, int(max_items_per_stage))
    result: dict[str, Any] = {}
    for key in _SNAPSHOT_ROOT_FIELDS:
        if key not in snapshot:
            continue
        value = snapshot[key]
        if key == "rrfParameters":
            sanitized = _sanitize_rrf_parameters(value)
        elif key == "filters":
            sanitized = _sanitize_snapshot_filters(value)
        elif key == "channels":
            sanitized = [str(channel) for channel in value] if isinstance(value, list) else []
        elif key == "featureFlags":
            sanitized = (
                {str(name): bool(enabled) for name, enabled in value.items()}
                if isinstance(value, dict)
                else {}
            )
        elif key == "chunkRetrievalDegraded":
            sanitized = bool(value)
        elif key == "latencyMs":
            sanitized = value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0
        elif key in {"configHash", "requestId"}:
            sanitized = value if isinstance(value, str) else None
        else:
            sanitized = value
        result[key] = sanitized

    stages = snapshot.get("stages")
    if isinstance(stages, dict):
        result["stages"] = {
            str(stage): [
                _sanitize_snapshot_item(item)
                for item in items[:cap]
                if isinstance(item, dict)
            ]
            for stage, items in stages.items()
            if isinstance(items, list)
        }
    else:
        result["stages"] = {}
    return result


def _sanitize_rrf_parameters(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    k = value.get("k")
    if isinstance(k, (int, float)) and not isinstance(k, bool):
        result["k"] = k
    weights = value.get("weights")
    if isinstance(weights, dict):
        result["weights"] = {
            str(channel): weight
            for channel, weight in weights.items()
            if isinstance(weight, (int, float)) and not isinstance(weight, bool)
        }
    return result


def _sanitize_snapshot_filters(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, Any] = {}
    for key in _SNAPSHOT_FILTER_FIELDS:
        item = value.get(key)
        if key == "scopeDocumentIds":
            result[key] = [str(value) for value in item] if isinstance(item, list) else None
        elif item is None or isinstance(item, str):
            result[key] = item
    return result


def _sanitize_snapshot_item(item: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in _SNAPSHOT_ITEM_FIELDS:
        value = item.get(key)
        if value is None:
            continue
        if key in {"channelScores", "channelRanks"}:
            if isinstance(value, dict):
                result[key] = {
                    str(channel): score
                    for channel, score in value.items()
                    if isinstance(score, (int, float)) and not isinstance(score, bool)
                }
        elif isinstance(value, (str, int, float, bool)):
            result[key] = value
    return result


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
