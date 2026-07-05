from contextvars import ContextVar
from uuid import uuid4

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)


def new_request_id() -> str:
    return f"req_{uuid4().hex}"


def set_request_id(request_id: str) -> None:
    _request_id.set(request_id)


def current_request_id() -> str:
    request_id = _request_id.get()
    if request_id is None:
        request_id = new_request_id()
        set_request_id(request_id)
    return request_id


def peek_request_id() -> str | None:
    """Current request id if one is set, else None (does not create one)."""
    return _request_id.get()

