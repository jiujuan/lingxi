from contextlib import asynccontextmanager
import time

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from server.app.api.openai_compatible import router as openai_router
from server.app.api.v1 import api_router
from server.app.core import metrics
from server.app.core.config import settings, validate_secret_config
from server.app.core.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from server.app.core.ids import current_request_id, new_request_id, set_request_id
from server.app.core.logging import configure_logging
from server.app.db.session import engine, get_db


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
    async def observability_middleware(request: Request, call_next):
        request_id = request.headers.get("x-request-id") or new_request_id()
        set_request_id(request_id)
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        route = request.scope.get("route")
        path = getattr(route, "path", request.url.path)
        metrics.observe_request(
            request.method, path, response.status_code, time.perf_counter() - started
        )
        return response

    @app.get("/health")
    def health(db: Session = Depends(get_db)) -> JSONResponse:
        checks = {"db": _check_db(db), "redis": _check_redis()}
        db_up = checks["db"] == "up"
        if all(state == "up" for state in checks.values()):
            status = "ok"
        elif db_up:
            status = "degraded"
        else:
            status = "down"
        return JSONResponse(
            status_code=200 if db_up else 503,
            content={"status": status, "checks": checks, "requestId": current_request_id()},
        )

    @app.get("/metrics")
    def prometheus_metrics() -> PlainTextResponse:
        return PlainTextResponse(
            metrics.render_prometheus(),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.include_router(api_router)
    app.include_router(openai_router)
    return app


def _check_db(db: Session) -> str:
    try:
        db.execute(text("SELECT 1"))
        return "up"
    except Exception:
        return "down"


def _check_redis() -> str:
    try:
        import redis

        client = redis.from_url(
            settings.redis_url, socket_connect_timeout=0.5, socket_timeout=0.5
        )
        client.ping()
        return "up"
    except Exception:
        return "down"


app = create_app()
