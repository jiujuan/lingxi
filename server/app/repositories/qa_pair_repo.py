from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.app.models.qa_pair import QaPair


class QaPairRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_by_document(self, document_id: str) -> list[QaPair]:
        statement = (
            select(QaPair)
            .where(
                QaPair.document_id == document_id,
                QaPair.deleted_at.is_(None),
                QaPair.status == "ACTIVE",
            )
            .order_by(QaPair.pair_index)
        )
        return list(self.session.scalars(statement).all())

    def list_by_document_page(
        self, tenant_id: str, document_id: str, page: int, page_size: int
    ) -> tuple[list[QaPair], int]:
        filters = (
            QaPair.tenant_id == tenant_id,
            QaPair.document_id == document_id,
            QaPair.deleted_at.is_(None),
            QaPair.status.in_(["ACTIVE", "EMBEDDING_FAILED"]),
        )
        total = self.session.scalar(select(func.count()).select_from(QaPair).where(*filters))
        statement = (
            select(QaPair)
            .where(*filters)
            .order_by(QaPair.pair_index)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.session.scalars(statement).all()), int(total or 0)
