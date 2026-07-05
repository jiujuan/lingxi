from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.schemas.chat import (
    ChatFeedbackRequest,
    ChatMessageListResponse,
    ChatMessageRunRequest,
    ChatSessionCreateRequest,
    ChatSessionListResponse,
    ChatSessionResponse,
)
from server.app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["chat"])


@router.get("/sessions", response_model=ChatSessionListResponse)
def list_sessions(
    context: AccessContext = Depends(require_permission("CHAT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return {"data": [_session_to_dict(item) for item in ChatService(db).list_sessions(context)]}


@router.post("/sessions", response_model=ChatSessionResponse)
def create_session(
    payload: ChatSessionCreateRequest,
    context: AccessContext = Depends(require_permission("CHAT_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    return _session_to_dict(ChatService(db).create_session(context, payload.title))


@router.get("/sessions/{session_id}/messages", response_model=ChatMessageListResponse)
def list_messages(
    session_id: str,
    context: AccessContext = Depends(require_permission("CHAT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "data": [
            _message_to_dict(item)
            for item in ChatService(db).list_messages(context, session_id)
        ]
    }


@router.post("/sessions/{session_id}/message-runs")
def create_message_run(
    session_id: str,
    payload: ChatMessageRunRequest,
    context: AccessContext = Depends(require_permission("CHAT_WRITE")),
    db: Session = Depends(get_db),
):
    stream = ChatService(db).stream_message_run(context, session_id, payload.content)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/messages/{message_id}/feedback")
def create_feedback(
    message_id: str,
    payload: ChatFeedbackRequest,
    context: AccessContext = Depends(require_permission("CHAT_WRITE")),
    db: Session = Depends(get_db),
) -> dict:
    message = ChatService(db).record_feedback(context, message_id, payload.feedback)
    return {"id": message.id, "status": message.status}


def _session_to_dict(item) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "status": item.status,
        "created_at": item.created_at.isoformat() if item.created_at else "",
        "updated_at": item.updated_at.isoformat() if item.updated_at else "",
    }


def _message_to_dict(item) -> dict:
    return {
        "id": item.id,
        "session_id": item.session_id,
        "role": item.role,
        "content": item.content,
        "status": item.status,
        "request_id": item.request_id,
        "created_at": item.created_at.isoformat() if item.created_at else "",
    }
