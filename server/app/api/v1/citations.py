from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext, require_permission
from server.app.db.session import get_db
from server.app.schemas.citation import CitationSourceResponse
from server.app.services.citation_service import CitationService

router = APIRouter(prefix="/citations", tags=["citations"])


@router.get("/{citation_id}/source", response_model=CitationSourceResponse)
def get_citation_source(
    citation_id: str,
    context: AccessContext = Depends(require_permission("CHAT_READ")),
    db: Session = Depends(get_db),
) -> dict:
    return CitationService(db).get_source(context, citation_id)
