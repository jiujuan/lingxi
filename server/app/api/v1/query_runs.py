from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.schemas.citation import CitationListResponse
from server.app.schemas.query_run import QueryRunResponse, RetrievalExplanationResponse
from server.app.services.citation_service import CitationService
from server.app.services.classification_path_service import ClassificationPathService
from server.app.services.retrieval_explanation_service import RetrievalExplanationService

router = APIRouter(prefix="/query-runs", tags=["query-runs"])


@router.get("/{run_id}", response_model=QueryRunResponse)
def get_query_run(
    run_id: str,
    context: AccessContext = Depends(require_permission("CHAT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    run = CitationService(db).get_run(context, run_id)
    return {
        "id": run.id,
        "run_id": run.run_id,
        "session_id": run.session_id,
        "question": run.question,
        "status": run.status,
        "latency_ms": run.latency_ms,
        "request_id": run.request_id,
        "retrieval_scope": ClassificationPathService(db).for_run_snapshot(
            context.tenant_id, run.retrieval_snapshot
        ),
    }


@router.get("/{run_id}/citations", response_model=CitationListResponse)
def list_query_run_citations(
    run_id: str,
    context: AccessContext = Depends(require_permission("CHAT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return {"data": CitationService(db).list_citations(context, run_id)}


@router.get(
    "/{run_id}/retrieval-explanation",
    response_model=RetrievalExplanationResponse,
)
def get_retrieval_explanation(
    run_id: str,
    context: AccessContext = Depends(require_permission("CHAT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return RetrievalExplanationService(db).get_explanation(context, run_id)
