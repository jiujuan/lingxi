from datetime import UTC, datetime
from math import ceil

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from server.app.core.errors import bad_request, forbidden, not_found
from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext
from server.app.models.document import (
    Document,
    DocumentAccessRule,
    DocumentAccessSubjectType,
    DocumentStatus,
)
from server.app.models.import_job import ImportJob
from server.app.models.logs import AuditLog, TaskRun
from server.app.models.qa_pair import DocumentChunk
from server.app.models.role import Role
from server.app.models.user import Department, User
from server.app.repositories.document_repo import DocumentRepository
from server.app.services.knowledge_category_service import KnowledgeCategoryService


class DocumentCenterService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.documents = DocumentRepository(session)

    def list_documents(
        self,
        context: AccessContext,
        *,
        keyword: str | None,
        file_type: str | None,
        status: str | None,
        department_id: str | None,
        role_id: str | None,
        space_id: str | None,
        classification_department_id: str | None,
        category_id: str | None,
        is_unclassified: bool | None,
        updated_after: datetime | None,
        updated_before: datetime | None,
        page: int,
        page_size: int,
    ) -> dict:
        items, total = self.documents.list_documents(
            context,
            keyword=keyword,
            file_type=file_type,
            status=status,
            department_id=department_id,
            role_id=role_id,
            space_id=space_id,
            classification_department_id=classification_department_id,
            category_id=category_id,
            is_unclassified=is_unclassified,
            updated_after=updated_after,
            updated_before=updated_before,
            page=page,
            page_size=page_size,
        )
        return {
            "data": [self.document_to_dict(context.tenant_id, item) for item in items],
            "pagination": self.pagination(page, page_size, total),
        }

    def summary(self, context: AccessContext) -> dict:
        synced_document_count, total_chunk_count = self.documents.summarize_documents(
            context
        )
        return {
            "synced_document_count": synced_document_count,
            "total_chunk_count": total_chunk_count,
        }

    def get_document(self, context: AccessContext, document_id: str) -> dict:
        document = self._get_document(context, document_id)
        data = self.document_to_dict(context.tenant_id, document)
        data.update(
            {
                "parser_version": document.parser_version,
                "object_key": document.object_key,
                "checksum": document.checksum,
                "processing_logs": [
                    self.task_run_to_dict(item)
                    for item in self.documents.list_task_runs(
                        context.tenant_id, data["latest_job"]["id"] if data["latest_job"] else None
                    )
                ],
            }
        )
        return data

    def list_chunks(
        self, context: AccessContext, document_id: str, page: int, page_size: int
    ) -> dict:
        document = self._get_document(context, document_id)
        chunks, total = self.documents.list_chunks_page(
            context.tenant_id, document.id, page, page_size
        )
        return {
            "data": [self.chunk_to_dict(item) for item in chunks],
            "pagination": self.pagination(page, page_size, total),
        }

    def update_permissions(
        self, context: AccessContext, document_id: str, permission: dict
    ) -> dict:
        document = self._get_document(context, document_id)
        before_snapshot = self.permission_to_dict(context.tenant_id, document.id)

        self.session.execute(
            delete(DocumentAccessRule).where(
                DocumentAccessRule.tenant_id == context.tenant_id,
                DocumentAccessRule.document_id == document.id,
            )
        )
        for rule in self._build_access_rules(context, document.id, permission):
            self.session.add(rule)

        after_snapshot = permission
        self._add_audit(
            context,
            action="DOCUMENT_PERMISSION_UPDATED",
            resource_id=document.id,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
        self.session.commit()
        return self.permission_to_dict(context.tenant_id, document.id)

    def update_classification(
        self, context: AccessContext, document_id: str, classification: object
    ) -> dict:
        document = self._get_document(context, document_id)
        classification_service = KnowledgeCategoryService(self.session)
        before_snapshot = self.classification_to_dict(context.tenant_id, document)
        validated = classification_service.validate_classification(
            context, classification
        )

        document.knowledge_space_id = (
            validated.knowledge_space.id if validated.knowledge_space else None
        )
        document.category_department_id = (
            validated.category_department.id
            if validated.category_department
            else None
        )
        document.knowledge_category_id = (
            validated.knowledge_category.id if validated.knowledge_category else None
        )

        after_snapshot = classification_service.classification_to_dict(
            context.tenant_id, document
        )
        self._add_audit(
            context,
            action="DOCUMENT_CLASSIFICATION_UPDATED",
            resource_id=document.id,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
        self.session.commit()
        return after_snapshot

    def bulk_update_classification(
        self, context: AccessContext, payload: object
    ) -> dict:
        document_ids = self._unique_document_ids(getattr(payload, "document_ids", []))
        classification = getattr(payload, "classification", None)

        documents = self.documents.list_authorized_documents_by_ids(
            context, document_ids
        )
        documents_by_id = {document.id: document for document in documents}
        if len(documents_by_id) != len(document_ids):
            raise forbidden("部分文档不存在或无权限，批量归类已取消")

        ordered_documents = [documents_by_id[document_id] for document_id in document_ids]
        classification_service = KnowledgeCategoryService(self.session)
        validated = classification_service.validate_classification(
            context, classification or {}
        )

        before_snapshots = {
            document.id: self.classification_to_dict(context.tenant_id, document)
            for document in ordered_documents
        }
        knowledge_space_id = (
            validated.knowledge_space.id if validated.knowledge_space else None
        )
        category_department_id = (
            validated.category_department.id
            if validated.category_department
            else None
        )
        knowledge_category_id = (
            validated.knowledge_category.id if validated.knowledge_category else None
        )

        updated_count = self.documents.bulk_update_classification(
            ordered_documents,
            knowledge_space_id=knowledge_space_id,
            category_department_id=category_department_id,
            knowledge_category_id=knowledge_category_id,
        )
        response_classification = (
            self.classification_to_dict(context.tenant_id, ordered_documents[0])
            if ordered_documents
            else None
        )

        for document in ordered_documents:
            self._add_audit(
                context,
                action="DOCUMENT_BULK_CLASSIFICATION_UPDATED",
                resource_id=document.id,
                before_snapshot=before_snapshots[document.id],
                after_snapshot=response_classification,
            )
        self.session.commit()
        return {
            "updated_count": updated_count,
            "document_ids": document_ids,
            "classification": response_classification,
        }

    def delete_document(self, context: AccessContext, document_id: str) -> dict:
        document = self._get_document(context, document_id)
        before_snapshot = {
            "status": document.status,
            "title": document.title,
        }
        document.status = DocumentStatus.DELETED
        document.deleted_at = datetime.now(UTC)
        self._add_audit(
            context,
            action="DOCUMENT_DELETED",
            resource_id=document.id,
            before_snapshot=before_snapshot,
            after_snapshot={"status": DocumentStatus.DELETED.value},
        )
        self.session.commit()
        return {"id": document.id, "status": DocumentStatus.DELETED.value}

    def document_to_dict(self, tenant_id: str, document: Document) -> dict:
        latest_job = self.documents.latest_import_job(tenant_id, document.id)
        return {
            "id": document.id,
            "title": document.title,
            "file_name": document.file_name,
            "file_type": document.file_type,
            "mime_type": document.mime_type,
            "file_size": document.file_size,
            "status": document.status,
            "parser_name": document.parser_name,
            "page_count": document.page_count,
            "qa_pair_count": document.qa_pair_count,
            "chunk_count": document.chunk_count,
            "permissions": self.permission_to_dict(tenant_id, document.id),
            "classification": self.classification_to_dict(tenant_id, document),
            "latest_job": self.job_to_dict(latest_job) if latest_job else None,
            "last_error_code": document.last_error_code,
            "last_error_message": document.last_error_message,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
        }

    def classification_to_dict(
        self, tenant_id: str, document: Document
    ) -> dict | None:
        if not (
            document.knowledge_space_id
            or document.category_department_id
            or document.knowledge_category_id
        ):
            return None
        return KnowledgeCategoryService(self.session).classification_to_dict(
            tenant_id, document
        )

    def permission_to_dict(self, tenant_id: str, document_id: str) -> dict:
        rules = self.documents.list_access_rules(tenant_id, document_id)
        department_ids = [
            item.subject_id
            for item in rules
            if item.subject_type == DocumentAccessSubjectType.DEPARTMENT
            and item.subject_id
        ]
        role_ids = [
            item.subject_id
            for item in rules
            if item.subject_type == DocumentAccessSubjectType.ROLE and item.subject_id
        ]
        user_ids = [
            item.subject_id
            for item in rules
            if item.subject_type == DocumentAccessSubjectType.USER and item.subject_id
        ]
        return {
            "all_authenticated": any(
                item.subject_type == DocumentAccessSubjectType.ALL_AUTHENTICATED
                for item in rules
            ),
            "departments": self._named_departments(tenant_id, department_ids),
            "roles": self._named_roles(tenant_id, role_ids),
            "users": self._named_users(tenant_id, user_ids),
        }

    @staticmethod
    def job_to_dict(job: ImportJob) -> dict:
        return {
            "id": job.id,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "retry_count": job.retry_count,
            "error_code": job.error_code,
            "error_message": job.error_message,
            "failed_stage": job.stage if job.status == "FAILED" else None,
            "retryable": job.status == "FAILED" and job.retry_count < job.max_retries,
        }

    @staticmethod
    def task_run_to_dict(task_run: TaskRun) -> dict:
        return {
            "id": task_run.id,
            "task_type": task_run.task_type,
            "queue_name": task_run.queue_name,
            "stage": task_run.stage,
            "status": task_run.status,
            "error": task_run.error,
            "request_id": task_run.request_id,
        }

    @staticmethod
    def chunk_to_dict(chunk: DocumentChunk) -> dict:
        return {
            "id": chunk.id,
            "document_id": chunk.document_id,
            "chunk_index": chunk.chunk_index,
            "title_path": chunk.title_path,
            "content": chunk.content,
            "page_no": chunk.page_no,
            "token_count": chunk.token_count,
            "source_locator": chunk.source_locator,
            "status": chunk.status,
        }

    @staticmethod
    def pagination(page: int, page_size: int, total: int) -> dict:
        return {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": ceil(total / page_size) if total else 0,
        }

    def _get_document(self, context: AccessContext, document_id: str) -> Document:
        document = self.documents.get_authorized_document(context, document_id)
        if document is None:
            raise not_found("文档不存在")
        return document


    @staticmethod
    def _unique_document_ids(document_ids: list[str]) -> list[str]:
        cleaned = [document_id.strip() for document_id in document_ids if document_id.strip()]
        if len(cleaned) != len(document_ids):
            raise bad_request("INVALID_DOCUMENT_IDS", "documentIds 不能为空")
        if len(set(cleaned)) != len(cleaned):
            raise bad_request("DUPLICATE_DOCUMENT_IDS", "documentIds 不能重复")
        return cleaned

    def _named_departments(self, tenant_id: str, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        rows = self.session.scalars(
            select(Department).where(
                Department.tenant_id == tenant_id,
                Department.id.in_(ids),
                Department.deleted_at.is_(None),
            )
        ).all()
        return [{"id": item.id, "name": item.name} for item in rows]

    def _named_roles(self, tenant_id: str, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        rows = self.session.scalars(
            select(Role).where(
                Role.tenant_id == tenant_id,
                Role.id.in_(ids),
                Role.deleted_at.is_(None),
            )
        ).all()
        return [{"id": item.id, "name": item.name} for item in rows]

    def _named_users(self, tenant_id: str, ids: list[str]) -> list[dict]:
        if not ids:
            return []
        rows = self.session.scalars(
            select(User).where(
                User.tenant_id == tenant_id,
                User.id.in_(ids),
                User.deleted_at.is_(None),
            )
        ).all()
        return [{"id": item.id, "name": item.name} for item in rows]

    @staticmethod
    def _build_access_rules(
        context: AccessContext, document_id: str, permission: dict
    ) -> list[DocumentAccessRule]:
        rules: list[DocumentAccessRule] = []
        if permission.get("allAuthenticated"):
            rules.append(
                DocumentAccessRule(
                    tenant_id=context.tenant_id,
                    document_id=document_id,
                    subject_type=DocumentAccessSubjectType.ALL_AUTHENTICATED,
                    subject_id=None,
                )
            )
        for subject_type, key in (
            (DocumentAccessSubjectType.DEPARTMENT, "departmentIds"),
            (DocumentAccessSubjectType.ROLE, "roleIds"),
            (DocumentAccessSubjectType.USER, "userIds"),
        ):
            for subject_id in permission.get(key, []):
                if subject_id:
                    rules.append(
                        DocumentAccessRule(
                            tenant_id=context.tenant_id,
                            document_id=document_id,
                            subject_type=subject_type,
                            subject_id=subject_id,
                        )
                    )
        return rules

    def _add_audit(
        self,
        context: AccessContext,
        *,
        action: str,
        resource_id: str,
        before_snapshot: dict | None,
        after_snapshot: dict | None,
    ) -> None:
        self.session.add(
            AuditLog(
                tenant_id=context.tenant_id,
                actor_id=context.user_id,
                action=action,
                resource_type="DOCUMENT",
                resource_id=resource_id,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
                request_id=current_request_id(),
            )
        )
