from sqlalchemy import func, select
from sqlalchemy.orm import Session

from server.app.models.document import Document, DocumentStatus
from server.app.models.knowledge_category import KnowledgeCategory, KnowledgeSpace


class KnowledgeSpaceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, space: KnowledgeSpace) -> KnowledgeSpace:
        self.session.add(space)
        self.session.flush()
        return space

    def get_for_tenant(self, tenant_id: str, space_id: str) -> KnowledgeSpace | None:
        return self.session.scalar(
            select(KnowledgeSpace).where(
                KnowledgeSpace.tenant_id == tenant_id,
                KnowledgeSpace.id == space_id,
                KnowledgeSpace.deleted_at.is_(None),
            )
        )

    def get_by_code(self, tenant_id: str, code: str) -> KnowledgeSpace | None:
        return self.session.scalar(
            select(KnowledgeSpace).where(
                KnowledgeSpace.tenant_id == tenant_id,
                KnowledgeSpace.code == code,
                KnowledgeSpace.deleted_at.is_(None),
            )
        )

    def list_for_tenant(self, tenant_id: str) -> list[KnowledgeSpace]:
        return list(
            self.session.scalars(
                select(KnowledgeSpace)
                .where(
                    KnowledgeSpace.tenant_id == tenant_id,
                    KnowledgeSpace.deleted_at.is_(None),
                )
                .order_by(
                    KnowledgeSpace.sort_order,
                    KnowledgeSpace.created_at,
                    KnowledgeSpace.id,
                )
            ).all()
        )

    def count_documents(self, tenant_id: str, space_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(Document.id)).where(
                    Document.tenant_id == tenant_id,
                    Document.deleted_at.is_(None),
                    Document.status != DocumentStatus.DELETED,
                    Document.knowledge_space_id == space_id,
                )
            )
            or 0
        )

    def delete(self, space: KnowledgeSpace) -> None:
        self.session.delete(space)
        self.session.flush()


class KnowledgeCategoryRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, category: KnowledgeCategory) -> KnowledgeCategory:
        self.session.add(category)
        self.session.flush()
        return category

    def get_for_tenant(
        self, tenant_id: str, category_id: str
    ) -> KnowledgeCategory | None:
        return self.session.scalar(
            select(KnowledgeCategory).where(
                KnowledgeCategory.tenant_id == tenant_id,
                KnowledgeCategory.id == category_id,
                KnowledgeCategory.deleted_at.is_(None),
            )
        )

    def get_by_code(
        self,
        tenant_id: str,
        space_id: str,
        department_id: str,
        code: str,
    ) -> KnowledgeCategory | None:
        return self.session.scalar(
            select(KnowledgeCategory).where(
                KnowledgeCategory.tenant_id == tenant_id,
                KnowledgeCategory.space_id == space_id,
                KnowledgeCategory.department_id == department_id,
                KnowledgeCategory.code == code,
                KnowledgeCategory.deleted_at.is_(None),
            )
        )

    def list_for_tenant(
        self,
        tenant_id: str,
        space_id: str | None = None,
        department_id: str | None = None,
    ) -> list[KnowledgeCategory]:
        statement = select(KnowledgeCategory).where(
            KnowledgeCategory.tenant_id == tenant_id,
            KnowledgeCategory.deleted_at.is_(None),
        )
        if space_id:
            statement = statement.where(KnowledgeCategory.space_id == space_id)
        if department_id:
            statement = statement.where(
                KnowledgeCategory.department_id == department_id
            )
        return list(
            self.session.scalars(
                statement.order_by(
                    KnowledgeCategory.sort_order,
                    KnowledgeCategory.created_at,
                    KnowledgeCategory.id,
                )
            ).all()
        )

    def count_documents(self, tenant_id: str, category_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(Document.id)).where(
                    Document.tenant_id == tenant_id,
                    Document.deleted_at.is_(None),
                    Document.status != DocumentStatus.DELETED,
                    Document.knowledge_category_id == category_id,
                )
            )
            or 0
        )

    def count_for_space(self, tenant_id: str, space_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(KnowledgeCategory.id)).where(
                    KnowledgeCategory.tenant_id == tenant_id,
                    KnowledgeCategory.space_id == space_id,
                    KnowledgeCategory.deleted_at.is_(None),
                )
            )
            or 0
        )

    def count_children(self, tenant_id: str, category_id: str) -> int:
        return int(
            self.session.scalar(
                select(func.count(KnowledgeCategory.id)).where(
                    KnowledgeCategory.tenant_id == tenant_id,
                    KnowledgeCategory.parent_id == category_id,
                    KnowledgeCategory.deleted_at.is_(None),
                )
            )
            or 0
        )

    def delete(self, category: KnowledgeCategory) -> None:
        self.session.delete(category)
        self.session.flush()
