from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext
from server.app.repositories.citation_repo import CitationRepository
from server.app.repositories.document_repo import DocumentRepository
from server.app.services.citation_service import CitationService


class RetrievalExplanationService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.repo = CitationRepository(session)

    def get_explanation(self, context: AccessContext, run_public_id: str) -> dict:
        run = CitationService(self.session).get_run(context, run_public_id)
        snapshot = run.retrieval_snapshot or {}
        authorized_doc_ids = {
            item.document_id
            for item in DocumentRepository(self.session).list_authorized_qa_pairs(context)
        }
        stages = {}
        for stage_name, candidates in (snapshot.get("stages") or {}).items():
            stages[stage_name] = [
                item
                for item in candidates
                if item.get("documentId") in authorized_doc_ids
                or bool(context.role_codes and "SYSTEM_ADMIN" in context.role_codes)
            ]
        return {
            "run_id": run.run_id,
            "question": run.question,
            "stages": stages,
            "filters": snapshot.get("filters") or {},
        }
