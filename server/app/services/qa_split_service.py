from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from server.app.core.errors import not_found
from server.app.core.config import settings
from server.app.core.secrets import decrypt_secret
import server.app.db.base  # noqa: F401
from server.app.integrations.model_providers.registry import build_provider_adapter
from server.app.models.document import Document, DocumentStatus
from server.app.models.import_job import ImportJob, ImportJobStatus
from server.app.models.logs import TaskRun
from server.app.models.model_config import ModelCapability, ModelConfig, ModelProvider
from server.app.models.qa_pair import DocumentChunk, QaPair
from server.app.services._batching import run_ordered
from server.app.services.import_service import enqueue_embedding_task  # re-exported
from server.app.services.qa_prompt_builder import build_qa_split_prompt

logger = logging.getLogger(__name__)

__all__ = [
    "QaSplitService",
    "QaSplitValidationError",
    "ValidatedQaItem",
    "validate_qa_split_output",
    "enqueue_embedding_task",
]


@dataclass(frozen=True)
class ValidatedQaItem:
    question: str
    answer: str
    quote: str
    page_no: int
    chunk_index: int | None = None


class QaSplitValidationError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.code = "QA_SPLIT_INVALID_OUTPUT"
        self.message = message


def validate_qa_split_output(raw_output: str) -> list[ValidatedQaItem]:
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError as exc:
        raise QaSplitValidationError("QA 拆分模型输出不是合法 JSON") from exc

    items = parsed.get("items") if isinstance(parsed, dict) else parsed
    if not isinstance(items, list) or not items:
        raise QaSplitValidationError("QA 拆分输出 items 为空")

    validated: list[ValidatedQaItem] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise QaSplitValidationError(f"第 {index + 1} 个 QA 项不是对象")
        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        quote = str(item.get("quote") or "").strip()
        page_no = item.get("pageNo", item.get("page_no"))
        chunk_index = item.get("chunkIndex", item.get("chunk_index"))
        if not question or not answer or not quote:
            raise QaSplitValidationError("QA 项缺少 question、answer 或 quote")
        if not isinstance(page_no, int) or page_no < 1:
            raise QaSplitValidationError("QA 项缺少合法 pageNo")
        if chunk_index is not None and (
            not isinstance(chunk_index, int) or chunk_index < 0
        ):
            raise QaSplitValidationError("QA 项 chunkIndex 不合法")
        validated.append(
            ValidatedQaItem(
                question=question,
                answer=answer,
                quote=quote,
                page_no=page_no,
                chunk_index=chunk_index,
            )
        )
    return validated


class QaSplitService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def split_import_job(self, job_id: str) -> ImportJob:
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
            task_type="split_document_qa_task",
            queue_name="qa",
            resource_type="IMPORT_JOB",
            resource_id=job.id,
            stage="QA_SPLITTING",
            status="RUNNING",
            error=None,
            request_id=None,
        )
        self.session.add(task_run)
        self.session.flush()

        job.status = ImportJobStatus.RUNNING.value
        job.stage = "QA_SPLITTING"
        job.progress = max(job.progress, 45)
        document.status = DocumentStatus.QA_SPLITTING
        self.session.flush()

        try:
            chunks = self._list_chunks(document.id)
            if not chunks:
                raise QaSplitValidationError("文档没有可拆分的 Chunk")
            model_config, provider = self._default_model(job.tenant_id)
            adapter = build_provider_adapter(
                provider.provider_type,
                provider.base_url,
                decrypt_secret(provider.encrypted_api_key),
                {**(provider.config or {}), **(model_config.config or {})},
                model_name=model_config.model_name,
                timeout_ms=model_config.timeout_ms,
            )
            prompt_batches = self._group_chunks(chunks)
            items = self._generate_qa_items(adapter, document, prompt_batches)
            self._replace_qa_pairs(job, document, chunks, items)

            document.qa_pair_count = len(items)
            document.status = DocumentStatus.EMBEDDING
            document.last_error_code = None
            document.last_error_message = None
            job.stage = "EMBEDDING"
            job.progress = 65
            job.status = ImportJobStatus.RUNNING.value
            job.error_code = None
            job.error_message = None
            task_run.status = "SUCCESS"
            task_run.error = None
            self.session.commit()
            return job
        except QaSplitValidationError as exc:
            self._mark_failed(job, document, task_run, exc.code, exc.message, True)
            return job
        except Exception:
            logger.exception("Unexpected error splitting QA for job %s", job.id)
            self._mark_failed(
                job,
                document,
                task_run,
                "QA_SPLIT_INTERNAL_ERROR",
                "QA 拆分失败",
                True,
            )
            return job

    def regenerate_document(self, tenant_id: str, document_id: str) -> ImportJob:
        job = self.session.scalar(
            select(ImportJob)
            .where(
                ImportJob.tenant_id == tenant_id,
                ImportJob.document_id == document_id,
                ImportJob.deleted_at.is_(None),
            )
            .order_by(ImportJob.created_at.desc())
        )
        if job is None:
            raise not_found("文档导入任务不存在")
        return self.split_import_job(job.id)

    def _default_model(self, tenant_id: str) -> tuple[ModelConfig, ModelProvider]:
        statement = (
            select(ModelConfig, ModelProvider)
            .join(ModelProvider, ModelProvider.id == ModelConfig.provider_id)
            .where(
                ModelConfig.tenant_id == tenant_id,
                ModelConfig.capability == ModelCapability.QA_SPLIT.value,
                ModelConfig.is_default.is_(True),
                ModelConfig.status == "ACTIVE",
                ModelConfig.deleted_at.is_(None),
                ModelProvider.status == "ACTIVE",
                ModelProvider.deleted_at.is_(None),
            )
        )
        row = self.session.execute(statement).first()
        if row is None:
            raise QaSplitValidationError("未配置默认 QA Split 模型")
        return row[0], row[1]

    def _group_chunks(self, chunks: list[DocumentChunk]) -> list[list[DocumentChunk]]:
        """Group chunks so each QA-split prompt stays within a size budget.

        A single document can hold far more text than a model's context window,
        so chunks are packed greedily into groups bounded by
        ``qa_split_max_batch_chars`` (an approximate token proxy). A chunk larger
        than the budget forms its own group.
        """
        max_chars = max(1, settings.qa_split_max_batch_chars)
        groups: list[list[DocumentChunk]] = []
        current: list[DocumentChunk] = []
        current_chars = 0
        for chunk in chunks:
            chunk_chars = len(chunk.content or "")
            if current and current_chars + chunk_chars > max_chars:
                groups.append(current)
                current = []
                current_chars = 0
            current.append(chunk)
            current_chars += chunk_chars
        if current:
            groups.append(current)
        return groups

    def _generate_qa_items(
        self,
        adapter,
        document: Document,
        groups: list[list[DocumentChunk]],
    ) -> list[ValidatedQaItem]:
        """Run QA split per chunk-group (bounded concurrency) and merge results.

        Each group is generated and validated independently; because every chunk
        carries its global ``chunkIndex`` in the prompt, merged items still map
        back to the correct source chunk in order.
        """

        def generate(group: list[DocumentChunk]) -> str:
            # ProviderError bubbles to the caller's generic handler
            # (QA_SPLIT_INTERNAL_ERROR, retryable) so the task layer retries.
            return adapter.generate_qa_pairs(build_qa_split_prompt(document, group))

        raw_outputs = run_ordered(
            groups, generate, settings.qa_split_max_concurrency
        )
        items: list[ValidatedQaItem] = []
        for raw in raw_outputs:
            items.extend(validate_qa_split_output(raw))
        return items

    def _list_chunks(self, document_id: str) -> list[DocumentChunk]:
        return list(
            self.session.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.deleted_at.is_(None),
                    DocumentChunk.status == "ACTIVE",
                )
                .order_by(DocumentChunk.chunk_index)
            ).all()
        )

    def _replace_qa_pairs(
        self,
        job: ImportJob,
        document: Document,
        chunks: list[DocumentChunk],
        items: list[ValidatedQaItem],
    ) -> None:
        self.session.execute(delete(QaPair).where(QaPair.document_id == document.id))
        chunk_by_index = {chunk.chunk_index: chunk for chunk in chunks}
        fallback_chunk = chunks[0]
        for index, item in enumerate(items):
            chunk = (
                chunk_by_index.get(item.chunk_index)
                if item.chunk_index is not None
                else fallback_chunk
            ) or fallback_chunk
            self.session.add(
                QaPair(
                    tenant_id=job.tenant_id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    job_id=job.id,
                    pair_index=index,
                    question=item.question,
                    answer=item.answer,
                    quote=item.quote,
                    page_no=item.page_no,
                    question_embedding=None,
                    search_text="",
                    token_count=len(item.question.split()) + len(item.answer.split()),
                    status="ACTIVE",
                    qa_metadata={"sourceChunkIndex": chunk.chunk_index},
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
        job.stage = "QA_SPLITTING"
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
