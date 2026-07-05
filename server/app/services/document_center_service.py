from datetime import UTC, datetime
from math import ceil

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from server.app.core.errors import not_found
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
            updated_after=updated_after,
            updated_before=updated_before,
            page=page,
            page_size=page_size,
        )
        return {
            "data": [self.document_to_dict(context.tenant_id, item) for item in items],
            "pagination": self.pagination(page, page_size, total),
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
            "latest_job": self.job_to_dict(latest_job) if latest_job else None,
            "last_error_code": document.last_error_code,
            "last_error_message": document.last_error_message,
            "created_at": document.created_at,
            "updated_at": document.updated_at,
        }

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
        before_snapshot: dict,
        after_snapshot: dict,
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
