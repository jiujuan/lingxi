from contextlib import asynccontextmanager
import logging
import time

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from server.app.api.openai_compatible import router as openai_router
from server.app.api.v1 import api_router
from server.app.core import metrics
from server.app.core.config import settings, validate_chunking_config, validate_secret_config
from server.app.core.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from server.app.core.ids import current_request_id, new_request_id, set_request_id
from server.app.core.logging import configure_logging
from server.app.db.session import engine, get_db
from server.app.repositories.api_call_log_repo import ApiCallLogRepository

logger = logging.getLogger(__name__)

# Only application traffic is worth persisting as an API call log; health,
# metrics and CORS preflight would just be noise.
_API_CALL_LOG_PREFIXES = ("/api/", "/v1/")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup
    yield
    # Shutdown: release pooled DB connections cleanly.
    engine.dispose()


def create_app() -> FastAPI:
    configure_logging()
    validate_secret_config()
    validate_chunking_config()
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
        elapsed = time.perf_counter() - started
        metrics.observe_request(
            request.method, path, response.status_code, elapsed
        )
        await _record_api_call(request, response, request_id, elapsed)
        return response

    @app.get("/health")
    def health(db: Session = Depends(get_db)) -> JSONResponse:
        checks = {
            "db": _check_db(db),
            "redis": _check_redis(),
            "mineru": _check_mineru(),
            "docling": _check_docling(),
        }
        db_up = checks["db"] == "up"
        # "unconfigured" services are excluded from the status calculation.
        gating = [state for state in checks.values() if state != "unconfigured"]
        if all(state == "up" for state in gating):
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


async def _record_api_call(request: Request, response, request_id: str, elapsed: float) -> None:
    """Persist one API call log row for application traffic.

    Endpoints and the auth dependency enrich ``request.state`` (tenant, key
    prefix, error code, metadata) as they run; this reads whatever made it
    there — unauthenticated/failed requests simply land with a NULL tenant.
    The write is offloaded to a worker thread (the ORM session is sync) and any
    failure is swallowed so logging can never break the request it describes.
    """
    if request.method == "OPTIONS":
        return
    raw_path = request.url.path
    if not raw_path.startswith(_API_CALL_LOG_PREFIXES):
        return
    # Streaming (SSE) responses keep the route's DB session open while the body
    # is produced; writing a log row from here would race that session (and
    # block the stream). Skip them — the non-streaming calls that dominate the
    # traffic still get recorded.
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        return
    state = request.state
    # Resolve the session factory through dependency_overrides so tests hit
    # their in-memory database instead of the process-wide engine.
    db_factory = request.app.dependency_overrides.get(get_db, get_db)
    payload = {
        "tenant_id": getattr(state, "log_tenant_id", None),
        "api_key_id": getattr(state, "log_api_key_id", None),
        "key_prefix": getattr(state, "log_key_prefix", None),
        "path": raw_path,
        "method": request.method,
        "status_code": response.status_code,
        "latency_ms": max(1, int(elapsed * 1000)),
        "error_code": getattr(state, "log_error_code", None),
        "request_id": request_id,
        "request_metadata": getattr(state, "log_metadata", None) or {},
    }
    await run_in_threadpool(_write_api_call_log, db_factory, payload)


def _write_api_call_log(db_factory, payload: dict) -> None:
    try:
        gen = db_factory()
        session = next(gen)
        try:
            ApiCallLogRepository(session).add(**payload)
            session.commit()
        finally:
            gen.close()
    except Exception:  # noqa: BLE001 - logging must never surface to the client
        logger.warning(
            "Failed to persist API call log for %s", payload.get("path"), exc_info=True
        )


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


def _check_mineru() -> str:
    # MinerU being down only degrades document parsing into retryable job
    # failures; it must never fail API readiness (no 503 from this check).
    base_url = (settings.mineru_base_url or "").rstrip("/")
    if not base_url:
        return "unconfigured"
    try:
        import httpx

        response = httpx.get(f"{base_url}/health", timeout=1.0)
        return "up" if response.status_code < 500 else "down"
    except Exception:
        return "down"


def _check_docling() -> str:
    # Same rule as MinerU: down degrades parsing only, never API readiness.
    base_url = (settings.docling_base_url or "").rstrip("/")
    if not base_url:
        return "unconfigured"
    try:
        import httpx

        headers = (
            {"X-Api-Key": settings.docling_api_key} if settings.docling_api_key else {}
        )
        response = httpx.get(f"{base_url}/health", headers=headers, timeout=1.0)
        return "up" if response.status_code < 500 else "down"
    except Exception:
        return "down"


app = create_app()
