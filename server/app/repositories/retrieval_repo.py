from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext
from server.app.models.qa_pair import QaPair
from server.app.repositories.document_repo import DocumentRepository
from server.app.schemas.retrieval import RetrievalAccessScope


class RetrievalRepository:
    def __init__(self, session: Session) -> None:
        self.document_repo = DocumentRepository(session)

    def list_authorized_candidates(
        self,
        context: AccessContext,
        access_scope: RetrievalAccessScope | None = None,
    ) -> list[QaPair]:
        candidates = self.document_repo.list_authorized_qa_pairs(context)
        if access_scope and access_scope.document_ids is not None:
            candidates = [
                item for item in candidates if item.document_id in access_scope.document_ids
            ]
        return candidates
