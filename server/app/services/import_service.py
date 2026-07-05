from base64 import b64decode
import binascii
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.core.config import settings
from server.app.core.errors import (
    bad_request,
    conflict,
    not_found,
    payload_too_large,
    unsupported_media_type,
)
from server.app.core.ids import current_request_id
from server.app.core.permissions import AccessContext
from server.app.integrations.storage.base import ObjectStorageAdapter
from server.app.integrations.storage.registry import get_storage_adapter
from server.app.models.document import (
    Document,
    DocumentAccessRule,
    DocumentAccessSubjectType,
    DocumentStatus,
)
from server.app.models.import_job import ImportJob, ImportJobFile, ImportJobStatus
from server.app.models.logs import AuditLog
from server.app.repositories.import_job_repo import ImportJobRepository


def enqueue_parse_task(job_id: str) -> bool:
    try:
        from server.app.tasks.parse_tasks import parse_document_task

        parse_document_task.apply_async(args=[job_id], queue="parse")
    except Exception:
        return False
    return True


def enqueue_qa_task(job_id: str) -> bool:
    try:
        from server.app.tasks.qa_tasks import split_document_qa_task

        split_document_qa_task.apply_async(args=[job_id], queue="qa")
    except Exception:
        return False
    return True


def enqueue_embedding_task(job_id: str) -> bool:
    try:
        from server.app.tasks.embedding_tasks import embed_qa_pairs_task

        embed_qa_pairs_task.apply_async(args=[job_id], queue="embedding")
    except Exception:
        return False
    return True


class ImportService:
    def __init__(
        self,
        session: Session,
        storage: ObjectStorageAdapter | None = None,
    ) -> None:
        self.session = session
        self.storage = storage or get_storage_adapter()
        self.jobs = ImportJobRepository(session)

    def create_job(
        self,
        context: AccessContext,
        *,
        title: str,
        permission: dict,
        parse_options: dict | None,
        processing_options: dict | None,
    ) -> ImportJob:
        document = Document(
            tenant_id=context.tenant_id,
            title=title.strip(),
            file_name="",
            file_type="UNKNOWN",
            mime_type="application/octet-stream",
            file_size=0,
            object_key=f"pending/{uuid4()}",
            checksum=f"pending:{uuid4()}",
            status=DocumentStatus.UPLOADED,
        )
        self.session.add(document)
        self.session.flush()

        for access_rule in self._build_access_rules(
            context, document.id, permission or {}
        ):
            self.session.add(access_rule)

        job = ImportJob(
            tenant_id=context.tenant_id,
            document_id=document.id,
            status=ImportJobStatus.PENDING.value,
            stage="CREATED",
            progress=0,
            options={
                "parseOptions": parse_options or {},
                "processingOptions": processing_options or {},
            },
        )
        self.jobs.add(job)
        self._add_audit(
            context,
            action="IMPORT_JOB_CREATED",
            resource_type="IMPORT_JOB",
            resource_id=job.id,
            after_snapshot={"documentId": document.id, "title": document.title},
        )
        self.session.commit()
        return job

    def bind_file(
        self,
        context: AccessContext,
        job_id: str,
        *,
        object_key: str,
        file_name: str,
        mime_type: str,
        file_size: int,
        checksum: str,
        content_base64: str | None,
    ) -> tuple[ImportJob, ImportJobFile]:
        job = self._get_job(context, job_id)
        document = self.session.get(Document, job.document_id)
        if document is None:
            raise not_found("导入任务关联文档不存在")

        self._validate_file_limits(file_name, file_size)
        self._ensure_unique_checksum(context.tenant_id, checksum, document.id)

        try:
            data = (
                b64decode(content_base64, validate=True)
                if content_base64 is not None
                else None
            )
        except (binascii.Error, ValueError) as exc:
            raise bad_request("INVALID_FILE_CONTENT", "文件内容不是合法 base64") from exc

        try:
            if data is not None:
                self.storage.put_object(object_key=object_key, data=data)
            else:
                self.storage.stat_object(object_key)
        except ValueError as exc:
            raise bad_request("INVALID_OBJECT_KEY", "object_key 不安全") from exc
        except FileNotFoundError as exc:
            raise not_found("对象存储文件不存在") from exc

        existing_files = self.jobs.list_files(context.tenant_id, job.id)
        if len(existing_files) >= settings.import_max_files_per_job:
            raise conflict("IMPORT_FILE_LIMIT_EXCEEDED", "导入任务文件数量已达上限")

        job_file = ImportJobFile(
            tenant_id=context.tenant_id,
            job_id=job.id,
            object_key=object_key,
            file_name=file_name,
            mime_type=mime_type,
            file_size=file_size,
            checksum=checksum,
        )
        self.session.add(job_file)

        document.file_name = file_name
        document.file_type = self._file_type(file_name)
        document.mime_type = mime_type
        document.file_size = file_size
        document.object_key = object_key
        document.checksum = checksum
        document.status = DocumentStatus.PARSING
        document.last_error_code = None
        document.last_error_message = None

        job.status = ImportJobStatus.RUNNING.value
        job.stage = "PARSING"
        job.progress = 10
        job.error_code = None
        job.error_message = None

        self._add_audit(
            context,
            action="IMPORT_FILE_BOUND",
            resource_type="IMPORT_JOB",
            resource_id=job.id,
            after_snapshot={
                "documentId": document.id,
                "objectKey": object_key,
                "fileName": file_name,
                "checksum": checksum,
            },
        )
        self.session.commit()

        enqueue_parse_task(job.id)
        return job, job_file

    def get_job(
        self, context: AccessContext, job_id: str
    ) -> tuple[ImportJob, ImportJobFile | None]:
        job = self._get_job(context, job_id)
        files = self.jobs.list_files(context.tenant_id, job.id)
        return job, files[0] if files else None

    def retry_job(self, context: AccessContext, job_id: str) -> tuple[ImportJob, ImportJobFile | None]:
        job = self._get_job(context, job_id)
        if job.status != ImportJobStatus.FAILED.value:
            raise conflict("STATE_CONFLICT", "只有失败任务可以重试")
        if job.retry_count >= job.max_retries:
            raise conflict("RETRY_LIMIT_EXCEEDED", "任务已达到最大重试次数")

        document = self.session.get(Document, job.document_id)
        if document is None:
            raise not_found("导入任务关联文档不存在")

        stage = job.stage if job.stage in {"PARSING", "QA_SPLITTING", "EMBEDDING"} else "PARSING"
        progress_by_stage = {"PARSING": 20, "QA_SPLITTING": 45, "EMBEDDING": 75}
        document_status_by_stage = {
            "PARSING": DocumentStatus.PARSING,
            "QA_SPLITTING": DocumentStatus.QA_SPLITTING,
            "EMBEDDING": DocumentStatus.EMBEDDING,
        }

        job.retry_count += 1
        job.status = ImportJobStatus.RUNNING.value
        job.stage = stage
        job.progress = progress_by_stage[stage]
        job.error_code = None
        job.error_message = None
        document.status = document_status_by_stage[stage]
        document.last_error_code = None
        document.last_error_message = None

        self._add_audit(
            context,
            action="IMPORT_JOB_RETRIED",
            resource_type="IMPORT_JOB",
            resource_id=job.id,
            after_snapshot={"documentId": document.id, "stage": stage},
        )
        self.session.commit()

        if stage == "QA_SPLITTING":
            enqueue_qa_task(job.id)
        elif stage == "EMBEDDING":
            enqueue_embedding_task(job.id)
        else:
            enqueue_parse_task(job.id)

        files = self.jobs.list_files(context.tenant_id, job.id)
        return job, files[0] if files else None

    @staticmethod
    def job_to_dict(job: ImportJob, job_file: ImportJobFile | None = None) -> dict:
        data = {
            "id": job.id,
            "document_id": job.document_id,
            "status": job.status,
            "stage": job.stage,
            "progress": job.progress,
            "retry_count": job.retry_count,
            "error_code": job.error_code,
            "error_message": job.error_message,
            "failed_stage": job.stage if job.status == ImportJobStatus.FAILED.value else None,
            "retryable": job.status == ImportJobStatus.FAILED.value
            and job.retry_count < job.max_retries,
            "file": None,
        }
        if job_file is not None:
            data["file"] = {
                "id": job_file.id,
                "object_key": job_file.object_key,
                "file_name": job_file.file_name,
                "mime_type": job_file.mime_type,
                "file_size": job_file.file_size,
                "checksum": job_file.checksum,
            }
        return data

    def _get_job(self, context: AccessContext, job_id: str) -> ImportJob:
        job = self.jobs.get_for_tenant(context.tenant_id, job_id)
        if job is None:
            raise not_found("导入任务不存在")
        return job

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
                rules.append(
                    DocumentAccessRule(
                        tenant_id=context.tenant_id,
                        document_id=document_id,
                        subject_type=subject_type,
                        subject_id=subject_id,
                    )
                )
        return rules

    @staticmethod
    def _file_type(file_name: str) -> str:
        suffix = Path(file_name).suffix.lower()
        if suffix in {".md", ".markdown"}:
            return "MARKDOWN"
        if suffix == ".txt":
            return "TEXT"
        return suffix.removeprefix(".").upper()

    @staticmethod
    def _validate_file_limits(file_name: str, file_size: int) -> None:
        suffix = Path(file_name).suffix.lower()
        allowed = {item.lower() for item in settings.upload_allowed_extensions}
        if suffix not in allowed:
            raise unsupported_media_type("不支持的文件类型")
        if file_size > settings.upload_max_file_size_bytes:
            raise payload_too_large("上传文件超过大小限制")

    def _ensure_unique_checksum(
        self, tenant_id: str, checksum: str, current_document_id: str
    ) -> None:
        duplicate = self.session.scalar(
            select(Document).where(
                Document.tenant_id == tenant_id,
                Document.checksum == checksum,
                Document.id != current_document_id,
                Document.deleted_at.is_(None),
                Document.status != DocumentStatus.DELETED,
            )
        )
        if duplicate is not None:
            raise conflict("DUPLICATE_DOCUMENT", "已存在相同 checksum 的文档")

    def _add_audit(
        self,
        context: AccessContext,
        *,
        action: str,
        resource_type: str,
        resource_id: str,
        after_snapshot: dict,
    ) -> None:
        self.session.add(
            AuditLog(
                tenant_id=context.tenant_id,
                actor_id=context.user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                before_snapshot=None,
                after_snapshot=after_snapshot,
                request_id=current_request_id(),
            )
        )
