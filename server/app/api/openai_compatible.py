from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from server.app.core.openai_errors import openai_error_response
from server.app.core.ids import current_request_id
from server.app.db.session import get_db
from server.app.schemas.openai_compatible import OpenAIChatCompletionRequest
from server.app.services.api_key_service import ApiKeyService
from server.app.services.openai_compatible_service import OpenAICompatibleService

router = APIRouter(prefix="/v1", tags=["openai-compatible"])
bearer_scheme = HTTPBearer(auto_error=False)


@router.post("/chat/completions")
def create_chat_completion(
    payload: OpenAIChatCompletionRequest,
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
):
    # Enrich request.state so the observability middleware records this call.
    # Start with the raw bearer prefix; upgrade to the resolved key's prefix
    # once authentication succeeds.
    request.state.log_key_prefix = (
        credentials.credentials[:16] if credentials else None
    )
    request.state.log_metadata = {"stream": payload.stream, "model": payload.model}
    try:
        if credentials is None:
            raise ApiKeyService._unauthorized("INVALID_API_KEY", "API Key 缺失")
        api_key = ApiKeyService(db).authenticate(
            credentials.credentials,
            required_scope="chat:completions",
        ).api_key
        request.state.log_tenant_id = api_key.tenant_id
        request.state.log_api_key_id = api_key.id
        request.state.log_key_prefix = api_key.key_prefix
        service = OpenAICompatibleService(db)
        if payload.stream:
            stream = service.stream_completion(api_key, payload)
            return StreamingResponse(
                stream,
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return service.create_completion(api_key, payload)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        error = detail.get("error") if isinstance(detail, dict) else {}
        request.state.log_error_code = (
            error.get("code") if isinstance(error, dict) else None
        )
        return JSONResponse(status_code=exc.status_code, content=openai_error_response(exc))
    except Exception:
        request.state.log_error_code = "MODEL_UNAVAILABLE"
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": "模型服务不可用",
                    "type": "server_error",
                    "code": "MODEL_UNAVAILABLE",
                },
                "request_id": current_request_id(),
            },
        )
