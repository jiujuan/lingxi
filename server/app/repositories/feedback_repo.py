from sqlalchemy.orm import Session
from sqlalchemy import select

from server.app.models.chat import ChatMessage


class FeedbackRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def mark_feedback(
        self, tenant_id: str, message_id: str, feedback: str
    ) -> ChatMessage | None:
        message = self.session.scalar(
            select(ChatMessage).where(
                ChatMessage.tenant_id == tenant_id,
                ChatMessage.id == message_id,
                ChatMessage.role == "ASSISTANT",
            )
        )
        if message is None:
            return None
        message.status = f"FEEDBACK_{feedback.upper()}"
        self.session.flush()
        return message
