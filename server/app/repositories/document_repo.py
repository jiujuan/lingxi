from datetime import datetime

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session

from server.app.core.permissions import AccessContext
from server.app.models.document import (
    Document,
    DocumentAccessRule,
    DocumentAccessSubjectType,
    DocumentStatus,
)
from server.app.models.import_job import ImportJob
from server.app.models.logs import TaskRun
from server.app.models.qa_pair import DocumentChunk
from server.app.models.qa_pair import QaPair


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_documents(
        self,
        context: AccessContext,
        *,
        keyword: str | None = None,
        file_type: str | None = None,
        status: str | None = None,
        department_id: str | None = None,
        role_id: str | None = None,
        updated_after: datetime | None = None,
        updated_before: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Document], int]:
        filters = self._document_filters(
            context,
            keyword=keyword,
            file_type=file_type,
            status=status,
            department_id=department_id,
            role_id=role_id,
            updated_after=updated_after,
            updated_before=updated_before,
        )
        total = self.session.scalar(
            select(func.count()).select_from(Document).where(*filters)
        )
        statement = (
            select(Document)
            .where(*filters)
            .order_by(Document.updated_at.desc(), Document.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.session.scalars(statement).all()), int(total or 0)

    def get_authorized_document(
        self, context: AccessContext, document_id: str
    ) -> Document | None:
        document = self.session.get(Document, document_id)
        if (
            document is None
            or document.tenant_id != context.tenant_id
            or document.deleted_at is not None
            or document.status == DocumentStatus.DELETED
        ):
            return None
        if self._is_system_admin(context) or self._can_access_document(
            context, document_id
        ):
            return document
        return None

    def list_chunks_page(
        self, tenant_id: str, document_id: str, page: int, page_size: int
    ) -> tuple[list[DocumentChunk], int]:
        filters = (
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.deleted_at.is_(None),
            DocumentChunk.status == "ACTIVE",
        )
        total = self.session.scalar(
            select(func.count()).select_from(DocumentChunk).where(*filters)
        )
        statement = (
            select(DocumentChunk)
            .where(*filters)
            .order_by(DocumentChunk.chunk_index)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list(self.session.scalars(statement).all()), int(total or 0)

    def list_access_rules(
        self, tenant_id: str, document_id: str
    ) -> list[DocumentAccessRule]:
        return list(
            self.session.scalars(
                select(DocumentAccessRule)
                .where(
                    DocumentAccessRule.tenant_id == tenant_id,
                    DocumentAccessRule.document_id == document_id,
                )
                .order_by(DocumentAccessRule.subject_type, DocumentAccessRule.subject_id)
            ).all()
        )

    def latest_import_job(
        self, tenant_id: str, document_id: str
    ) -> ImportJob | None:
        return self.session.scalar(
            select(ImportJob)
            .where(
                ImportJob.tenant_id == tenant_id,
                ImportJob.document_id == document_id,
                ImportJob.deleted_at.is_(None),
            )
            .order_by(ImportJob.created_at.desc())
        )

    def list_task_runs(
        self, tenant_id: str, job_id: str | None
    ) -> list[TaskRun]:
        if job_id is None:
            return []
        return list(
            self.session.scalars(
                select(TaskRun)
                .where(
                    TaskRun.tenant_id == tenant_id,
                    TaskRun.resource_type == "IMPORT_JOB",
                    TaskRun.resource_id == job_id,
                )
                .order_by(TaskRun.id.desc())
            ).all()
        )

    def list_authorized_qa_pairs(self, context: AccessContext) -> list[QaPair]:
        filters = [
            Document.tenant_id == context.tenant_id,
            QaPair.tenant_id == context.tenant_id,
            Document.status == DocumentStatus.READY,
            Document.deleted_at.is_(None),
            QaPair.deleted_at.is_(None),
            QaPair.status == "ACTIVE",
        ]
        if not self._is_system_admin(context):
            filters.append(self._access_exists(context))
        statement = (
            select(QaPair)
            .join(Document, Document.id == QaPair.document_id)
            .where(*filters)
            .order_by(QaPair.document_id, QaPair.pair_index)
        )
        return list(self.session.scalars(statement).unique().all())

    def _document_filters(
        self,
        context: AccessContext,
        *,
        keyword: str | None,
        file_type: str | None,
        status: str | None,
        department_id: str | None,
        role_id: str | None,
        updated_after: datetime | None,
        updated_before: datetime | None,
    ) -> list:
        filters: list = [
            Document.tenant_id == context.tenant_id,
            Document.deleted_at.is_(None),
            Document.status != DocumentStatus.DELETED,
        ]
        if not self._is_system_admin(context):
            filters.append(self._access_exists(context))
        if keyword:
            pattern = f"%{keyword.strip()}%"
            filters.append(
                or_(Document.title.ilike(pattern), Document.file_name.ilike(pattern))
            )
        if file_type:
            filters.append(Document.file_type == file_type.upper())
        if status:
            filters.append(Document.status == status.upper())
        if department_id:
            filters.append(
                self._specific_access_exists(
                    DocumentAccessSubjectType.DEPARTMENT, department_id
                )
            )
        if role_id:
            filters.append(
                self._specific_access_exists(DocumentAccessSubjectType.ROLE, role_id)
            )
        if updated_after:
            filters.append(Document.updated_at >= updated_after)
        if updated_before:
            filters.append(Document.updated_at <= updated_before)
        return filters

    def _can_access_document(self, context: AccessContext, document_id: str) -> bool:
        return bool(
            self.session.scalar(
                select(
                    exists()
                    .where(
                        DocumentAccessRule.tenant_id == context.tenant_id,
                        DocumentAccessRule.document_id == document_id,
                    )
                    .where(or_(*self._access_conditions(context)))
                )
            )
        )

    def _access_exists(self, context: AccessContext):
        return exists().where(
            DocumentAccessRule.tenant_id == context.tenant_id,
            DocumentAccessRule.document_id == Document.id,
            or_(*self._access_conditions(context)),
        )

    @staticmethod
    def _specific_access_exists(
        subject_type: DocumentAccessSubjectType, subject_id: str
    ):
        return exists().where(
            DocumentAccessRule.document_id == Document.id,
            DocumentAccessRule.subject_type == subject_type,
            DocumentAccessRule.subject_id == subject_id,
        )

    @staticmethod
    def _access_conditions(context: AccessContext) -> list:
        access_conditions = [
            DocumentAccessRule.subject_type
            == DocumentAccessSubjectType.ALL_AUTHENTICATED
        ]
        department_ids = list(context.department_ids or [])
        if context.department_id and context.department_id not in department_ids:
            department_ids.append(context.department_id)
        if department_ids:
            access_conditions.append(
                and_(
                    DocumentAccessRule.subject_type
                    == DocumentAccessSubjectType.DEPARTMENT,
                    DocumentAccessRule.subject_id.in_(department_ids),
                )
            )
        if context.role_ids:
            access_conditions.append(
                and_(
                    DocumentAccessRule.subject_type == DocumentAccessSubjectType.ROLE,
                    DocumentAccessRule.subject_id.in_(context.role_ids),
                )
            )
        access_conditions.append(
            and_(
                DocumentAccessRule.subject_type == DocumentAccessSubjectType.USER,
                DocumentAccessRule.subject_id == context.user_id,
            )
        )
        return access_conditions

    @staticmethod
    def _is_system_admin(context: AccessContext) -> bool:
        return bool(context.role_codes and "SYSTEM_ADMIN" in context.role_codes)
