from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException

from server.app.api.openai_compatible import router as openai_router
from server.app.api.v1 import api_router
from server.app.core.config import validate_secret_config
from server.app.core.errors import http_exception_handler
from server.app.core.ids import current_request_id, new_request_id, set_request_id
from server.app.core.logging import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    validate_secret_config()
    app = FastAPI(title="Lingxi Knowledge Base", version="1.1.0")

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or new_request_id()
        set_request_id(request_id)
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "requestId": current_request_id()}

    app.add_exception_handler(HTTPException, http_exception_handler)
    app.include_router(api_router)
    app.include_router(openai_router)
    return app


app = create_app()
