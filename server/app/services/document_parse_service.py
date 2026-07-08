from datetime import UTC, datetime
import hashlib
import logging
import re

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from server.app.integrations.parsers.base import (
    ParseRequest,
    ParseSource,
    ParserAdapter,
    ParserError,
)
from server.app.integrations.parsers.registry import get_parser_chain
from server.app.integrations.storage.base import ObjectStorageAdapter
from server.app.integrations.storage.registry import get_storage_adapter
from server.app.models.document import Document, DocumentStatus
from server.app.models.import_job import ImportJob, ImportJobFile, ImportJobStatus, ParseArtifact
from server.app.models.logs import TaskRun
from server.app.models.qa_pair import DocumentChunk

logger = logging.getLogger(__name__)

# CJK-aware token proxy: one token per ideograph, one per alphanumeric run.
# ``len(content.split())`` counted whole Chinese paragraphs as a single token.
_TOKEN_COUNT_RE = re.compile(r"[一-鿿]|[^\W_]+")


def _count_tokens(content: str) -> int:
    return len(_TOKEN_COUNT_RE.findall(content))


class DocumentParseService:
    def __init__(
        self,
        session: Session,
        storage: ObjectStorageAdapter | None = None,
        parsers: list[ParserAdapter] | None = None,
    ) -> None:
        self.session = session
        self.storage = storage or get_storage_adapter()
        self.parsers = parsers or get_parser_chain()

    def parse_import_job(self, job_id: str) -> ImportJob:
        job = self.session.get(ImportJob, job_id)
        if job is None:
            raise ValueError("Import job does not exist")
        document = self.session.get(Document, job.document_id)
        if document is None:
            raise ValueError("Import job document does not exist")

        # Idempotency: a duplicate delivery of an already-finished job is a no-op.
        if job.status == ImportJobStatus.COMPLETED.value:
            return job

        task_run = TaskRun(
            tenant_id=job.tenant_id,
            task_type="parse_document_task",
            queue_name="parse",
            resource_type="IMPORT_JOB",
            resource_id=job.id,
            stage="PARSING",
            status="RUNNING",
            error=None,
            request_id=None,
        )
        self.session.add(task_run)
        self.session.flush()

        job.status = ImportJobStatus.RUNNING.value
        job.stage = "PARSING"
        job.progress = max(job.progress, 20)
        document.status = DocumentStatus.PARSING
        self.session.flush()

        try:
            job_file = self._get_job_file(job)
            content = self.storage.get_object(job_file.object_key)
            source = ParseSource(
                file_name=job_file.file_name,
                mime_type=job_file.mime_type,
                object_key=job_file.object_key,
                content=content,
            )
            parser = self._select_parser(source)
            parsed = parser.parse(ParseRequest(source=source, options=job.options or {}))
            if not parsed.blocks:
                # No content blocks means the QA-split stage would later fail
                # with an opaque "no chunk to split" error. Fail here instead,
                # at the stage that has the context, with an actionable cause:
                # scanned/image-only PDFs (OCR off), heading-only or empty
                # documents all extract to zero retrievable text blocks.
                # Not retryable — re-parsing the same file yields the same
                # empty result unless the upload or OCR config changes.
                raise ParserError(
                    "PARSER_NO_CONTENT",
                    "文档解析后未提取到任何文本内容，可能是扫描件/纯图片（需开启 OCR）"
                    "或文档为空/仅有标题",
                    retryable=False,
                )
            self._replace_parse_outputs(job, document, parsed.markdown, parsed.blocks)

            document.parser_name = parsed.parser_name
            document.parser_version = parsed.parser_version
            document.page_count = parsed.page_count
            document.chunk_count = len(parsed.blocks)
            document.status = DocumentStatus.QA_SPLITTING
            document.last_error_code = None
            document.last_error_message = None

            job.status = ImportJobStatus.RUNNING.value
            job.stage = "QA_SPLITTING"
            job.progress = 40
            job.error_code = None
            job.error_message = None

            task_run.status = "SUCCESS"
            task_run.error = None
            self.session.commit()
            return job
        except ParserError as exc:
            self._mark_failed(job, document, task_run, exc.code, exc.message, exc.retryable)
            return job
        except Exception:
            logger.exception("Unexpected error parsing import job %s", job.id)
            self._mark_failed(
                job,
                document,
                task_run,
                "PARSER_INTERNAL_ERROR",
                "文档解析失败",
                True,
            )
            return job

    def _get_job_file(self, job: ImportJob) -> ImportJobFile:
        job_file = self.session.scalar(
            select(ImportJobFile)
            .where(
                ImportJobFile.tenant_id == job.tenant_id,
                ImportJobFile.job_id == job.id,
            )
            .order_by(ImportJobFile.id)
        )
        if job_file is None:
            raise ParserError("IMPORT_FILE_MISSING", "导入任务未绑定文件", retryable=True)
        return job_file

    def _select_parser(self, source: ParseSource) -> ParserAdapter:
        for parser in self.parsers:
            if parser.supports(source):
                return parser
        raise ParserError("UNSUPPORTED_FILE_TYPE", "没有可用解析器支持该文件类型")

    def _replace_parse_outputs(
        self,
        job: ImportJob,
        document: Document,
        markdown: str,
        blocks,
    ) -> None:
        self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
        )
        self.session.execute(
            delete(ParseArtifact).where(
                ParseArtifact.document_id == document.id,
                ParseArtifact.job_id == job.id,
            )
        )

        artifact_key = f"artifacts/{document.id}/parsed.md"
        data = markdown.encode("utf-8")
        self.storage.put_object(artifact_key, data)
        self.session.add(
            ParseArtifact(
                tenant_id=job.tenant_id,
                document_id=document.id,
                job_id=job.id,
                artifact_type="PARSED_MARKDOWN",
                object_key=artifact_key,
                content_hash=hashlib.sha256(data).hexdigest(),
                artifact_metadata={},
            )
        )

        for block in blocks:
            self.session.add(
                DocumentChunk(
                    tenant_id=job.tenant_id,
                    document_id=document.id,
                    job_id=job.id,
                    chunk_index=block.index,
                    title_path=block.title_path,
                    content=block.content,
                    page_no=block.page_no,
                    token_count=_count_tokens(block.content),
                    source_locator=block.source_locator,
                    status="ACTIVE",
                )
            )

    def _mark_failed(
        self,
        job: ImportJob,
        document: Document,
        task_run: TaskRun,
        code: str,
        message: str,
        retryable: bool,
    ) -> None:
        document.status = DocumentStatus.FAILED
        document.last_error_code = code
        document.last_error_message = message
        job.status = ImportJobStatus.FAILED.value
        job.stage = "PARSING"
        job.error_code = code
        job.error_message = message
        task_run.status = "FAILED"
        task_run.error = {
            "code": code,
            "message": message,
            "retryable": retryable,
            "failedAt": datetime.now(UTC).isoformat(),
        }
        self.session.commit()
