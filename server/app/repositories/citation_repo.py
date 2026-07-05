from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.models.chat import QueryCitation, QueryRun


class CitationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get_run_by_public_id(self, tenant_id: str, run_id: str) -> QueryRun | None:
        return self.session.scalar(
            select(QueryRun).where(
                QueryRun.tenant_id == tenant_id,
                QueryRun.run_id == run_id,
            )
        )

    def get_citation(self, tenant_id: str, citation_id: str) -> QueryCitation | None:
        return self.session.scalar(
            select(QueryCitation).where(
                QueryCitation.tenant_id == tenant_id,
                QueryCitation.id == citation_id,
            )
        )

    def list_citations(self, tenant_id: str, run_db_id: str) -> list[QueryCitation]:
        return list(
            self.session.scalars(
                select(QueryCitation)
                .where(
                    QueryCitation.tenant_id == tenant_id,
                    QueryCitation.run_id == run_db_id,
                )
                .order_by(QueryCitation.rank, QueryCitation.id)
            ).all()
        )
