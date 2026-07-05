from sqlalchemy.orm import Session

from server.app.models.chat import QueryCitation, QueryRun


class QueryRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_run(
        self,
        *,
        tenant_id: str,
        run_id: str,
        session_id: str | None,
        user_message_id: str | None,
        question: str,
        request_id: str,
        retrieval_snapshot: dict,
    ) -> QueryRun:
        run = QueryRun(
            tenant_id=tenant_id,
            run_id=run_id,
            session_id=session_id,
            user_message_id=user_message_id,
            question=question,
            status="RUNNING",
            retrieval_snapshot=retrieval_snapshot,
            token_usage={},
            request_id=request_id,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def add_citation(
        self,
        *,
        tenant_id: str,
        run_db_id: str,
        message_id: str | None,
        document_id: str | None,
        qa_pair_id: str | None,
        quote: str,
        rank: int,
        snapshot: dict,
    ) -> QueryCitation:
        citation = QueryCitation(
            tenant_id=tenant_id,
            run_id=run_db_id,
            message_id=message_id,
            document_id=document_id,
            qa_pair_id=qa_pair_id,
            quote=quote,
            rank=rank,
            snapshot=snapshot,
        )
        self.session.add(citation)
        self.session.flush()
        return citation
