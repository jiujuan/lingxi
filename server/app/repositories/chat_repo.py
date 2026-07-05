from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.models.chat import ChatMessage, ChatSession


class ChatRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_session(
        self, tenant_id: str, user_id: str, title: str | None
    ) -> ChatSession:
        chat_session = ChatSession(
            tenant_id=tenant_id,
            user_id=user_id,
            title=title or "新会话",
            status="ACTIVE",
        )
        self.session.add(chat_session)
        self.session.flush()
        return chat_session

    def list_sessions(self, tenant_id: str, user_id: str) -> list[ChatSession]:
        return list(
            self.session.scalars(
                select(ChatSession)
                .where(
                    ChatSession.tenant_id == tenant_id,
                    ChatSession.user_id == user_id,
                    ChatSession.status == "ACTIVE",
                )
                .order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc())
            ).all()
        )

    def get_session(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> ChatSession | None:
        return self.session.scalar(
            select(ChatSession).where(
                ChatSession.id == session_id,
                ChatSession.tenant_id == tenant_id,
                ChatSession.user_id == user_id,
                ChatSession.status == "ACTIVE",
            )
        )

    def add_message(
        self,
        tenant_id: str,
        session_id: str,
        role: str,
        content: str,
        request_id: str | None,
        status: str = "CREATED",
    ) -> ChatMessage:
        now = datetime.now(UTC)
        message = ChatMessage(
            tenant_id=tenant_id,
            session_id=session_id,
            role=role,
            content=content,
            status=status,
            request_id=request_id,
            created_at=now,
            updated_at=now,
        )
        self.session.add(message)
        self.session.flush()
        return message

    def list_messages(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> list[ChatMessage]:
        chat_session = self.get_session(tenant_id, user_id, session_id)
        if chat_session is None:
            return []
        return list(
            self.session.scalars(
                select(ChatMessage)
                .where(
                    ChatMessage.tenant_id == tenant_id,
                    ChatMessage.session_id == session_id,
                )
                .order_by(ChatMessage.created_at, ChatMessage.id)
            ).all()
        )
