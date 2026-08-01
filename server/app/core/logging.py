from datetime import UTC, datetime
import json
import logging
import os
import sys

from server.app.core.ids import peek_request_id

_LINGXI_HANDLER_MARKER = "_lingxi_configured_handler"


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every log record for correlation."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = peek_request_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "requestId": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def configure_logging() -> None:
    """Configure root logging.

    Defaults to structured JSON (one object per line) with the request id
    injected for correlation. Set LOG_FORMAT=text for human-friendly local dev.
    Idempotent: re-running replaces the handler.
    """
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler(sys.stdout)
    setattr(handler, _LINGXI_HANDLER_MARKER, True)
    handler.addFilter(RequestIdFilter())
    if os.getenv("LOG_FORMAT", "json").lower() == "text":
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s"
            )
        )
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    for existing_handler in tuple(root.handlers):
        if getattr(existing_handler, _LINGXI_HANDLER_MARKER, False):
            root.removeHandler(existing_handler)
            existing_handler.close()
    root.setLevel(level)
    root.addHandler(handler)
