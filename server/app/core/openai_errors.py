from fastapi import HTTPException

from server.app.core.ids import current_request_id


def openai_error_response(exc: HTTPException) -> dict:
    detail = exc.detail if isinstance(exc.detail, dict) else {}
    error = detail.get("error") if isinstance(detail, dict) else None
    code = error.get("code") if isinstance(error, dict) else "REQUEST_ERROR"
    message = error.get("message") if isinstance(error, dict) else str(exc.detail)
    return {
        "error": {
            "message": message,
            "type": _error_type(exc.status_code),
            "code": code,
        },
        "request_id": detail.get("requestId") or current_request_id(),
    }


def _error_type(status_code: int) -> str:
    if status_code == 401:
        return "authentication_error"
    if status_code == 403:
        return "permission_error"
    if status_code == 429:
        return "rate_limit_error"
    if status_code >= 500:
        return "server_error"
    return "invalid_request_error"
