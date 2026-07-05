import hashlib

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.models.chat import MissedQuestion


class MissedQuestionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(self, tenant_id: str, question: str, metadata: dict) -> MissedQuestion:
        question_hash = hashlib.sha256(
            f"{tenant_id}:{question.strip()}".encode("utf-8")
        ).hexdigest()
        missed = self.session.scalar(
            select(MissedQuestion).where(
                MissedQuestion.tenant_id == tenant_id,
                MissedQuestion.question_hash == question_hash,
                MissedQuestion.status == "OPEN",
            )
        )
        if missed is None:
            missed = MissedQuestion(
                tenant_id=tenant_id,
                question_hash=question_hash,
                question_text=question.strip(),
                count=1,
                missed_metadata=metadata,
            )
            self.session.add(missed)
        else:
            missed.count += 1
            missed.missed_metadata = {**(missed.missed_metadata or {}), **metadata}
        self.session.flush()
        return missed
