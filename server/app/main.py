from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from server.app.api.openai_compatible import router as openai_router
from server.app.api.v1 import api_router
from server.app.core.config import settings, validate_secret_config
from server.app.core.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from server.app.core.ids import current_request_id, new_request_id, set_request_id
from server.app.core.logging import configure_logging
from server.app.db.session import engine


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup
    yield
    # Shutdown: release pooled DB connections cleanly.
    engine.dispose()


def create_app() -> FastAPI:
    configure_logging()
    validate_secret_config()
    app = FastAPI(title="Lingxi Knowledge Base", version="1.1.0", lifespan=lifespan)

    origins = list(settings.cors_allow_origins)
    allow_all = "*" in origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        # Credentials cannot be combined with a wildcard origin per the CORS spec.
        allow_credentials=not allow_all,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["x-request-id"],
    )

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
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(api_router)
    app.include_router(openai_router)
    return app


app = create_app()
