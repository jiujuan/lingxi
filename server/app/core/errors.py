from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from server.app.core.ids import current_request_id


def error_payload(code: str, message: str, details: dict | None = None) -> dict:
    return {
        "error": {"code": code, "message": message, "details": details or {}},
        "requestId": current_request_id(),
    }


def api_error(
    status_code: int, code: str, message: str, details: dict | None = None
) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail=error_payload(code, message, details)
    )


def bad_request(code: str, message: str, details: dict | None = None) -> HTTPException:
    return api_error(400, code, message, details)


def forbidden(message: str = "权限不足") -> HTTPException:
    return HTTPException(status_code=403, detail=error_payload("FORBIDDEN", message))


def not_found(message: str = "资源不存在") -> HTTPException:
    return api_error(404, "NOT_FOUND", message)


def conflict(code: str, message: str, details: dict | None = None) -> HTTPException:
    return api_error(409, code, message, details)


def payload_too_large(message: str = "上传文件过大") -> HTTPException:
    return api_error(413, "PAYLOAD_TOO_LARGE", message)


def unsupported_media_type(message: str = "不支持的文件类型") -> HTTPException:
    return api_error(415, "UNSUPPORTED_FILE_TYPE", message)


def unauthenticated(message: str = "未认证") -> HTTPException:
    return HTTPException(
        status_code=401, detail=error_payload("UNAUTHENTICATED", message)
    )


def service_unavailable(
    message: str = "服务暂时不可用", code: str = "SERVICE_UNAVAILABLE"
) -> HTTPException:
    return api_error(503, code, message)


async def http_exception_handler(
    _request: Request, exc: HTTPException
) -> JSONResponse:
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        return JSONResponse(status_code=exc.status_code, content=exc.detail)

    code = "INTERNAL_ERROR" if exc.status_code >= 500 else "REQUEST_ERROR"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code, str(exc.detail)),
    )
