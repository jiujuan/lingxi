from datetime import UTC, datetime
import hashlib
import logging
import re
from time import perf_counter
from uuid import uuid4

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from server.app.core import metrics
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
from server.app.services.chunking import (
    AtomicBlock,
    ChunkPolicy,
    ChunkingService,
    LocalTokenCounter,
    to_json_value,
)

logger = logging.getLogger(__name__)

# CJK-aware token proxy: one token per ideograph, one per alphanumeric run.
# ``len(content.split())`` counted whole Chinese paragraphs as a single token.
_TOKEN_COUNT_RE = re.compile(r"[一-鿿]|[^\W_]+")


def log_chunking_observability(
    *,
    tenant_id: str,
    document_id: str,
    job_id: str,
    parser_name: str,
    parser_version: str,
    policy: ChunkPolicy,
    result,
    duration_seconds: float,
) -> None:
    """Emit safe adaptive-chunking audit fields and aggregate health metrics."""

    token_counts_by_block_type: dict[str, list[int]] = {}
    for child in result.children:
        token_counts_by_block_type.setdefault(child.block_type.value, []).append(
            child.token_count
        )
    warning_codes = [warning.code for warning in result.warnings]
    tiny_chunk_count = warning_codes.count("TINY_CHUNK_UNMERGEABLE")
    skipped_image_count = warning_codes.count("IMAGE_WITHOUT_TEXT_SKIPPED")
    metrics.observe_chunking(
        duration_seconds=duration_seconds,
        token_counts_by_block_type=token_counts_by_block_type,
        tiny_count=tiny_chunk_count,
        oversized_count=result.stats.oversized_count,
        merge_count=result.stats.merge_count,
        split_count=result.stats.split_count,
    )
    logger.info(
        "adaptive chunking completed",
        extra={
            "tenant_id": tenant_id,
            "document_id": document_id,
            "job_id": job_id,
            "parser_name": parser_name,
            "parser_version": parser_version,
            "config_hash": policy.config_hash,
            "chunker_name": policy.name,
            "chunker_version": policy.version,
            "duration_ms": round(duration_seconds * 1000),
            "atomic_block_count": result.stats.input_block_count,
            "skipped_block_count": result.stats.skipped_block_count,
            "child_count": result.stats.child_count,
            "parent_count": result.stats.parent_count,
            "total_token_count": result.stats.total_token_count,
            "warning_count": len(result.warnings),
            # Canonical Task 18 structured-log contract.  Keep existing
            # snake_case fields above for operational compatibility while
            # emitting the specification's camelCase audit names.
            "tenantId": tenant_id,
            "documentId": document_id,
            "jobId": job_id,
            "parserName": parser_name,
            "parserVersion": parser_version,
            "chunkerName": policy.name,
            "chunkerVersion": policy.version,
            "configHash": policy.config_hash,
            "tokenizerName": policy.tokenizer_name,
            "atomicBlockCount": result.stats.input_block_count,
            "childCount": result.stats.child_count,
            "parentCount": result.stats.parent_count,
            "mergeCount": result.stats.merge_count,
            "splitCount": result.stats.split_count,
            "tinyChunkCount": tiny_chunk_count,
            "oversizedChunkCount": result.stats.oversized_count,
            "skippedImageCount": skipped_image_count,
            "featureFlags": {"adaptiveChunkingEnabled": True},
        },
    )


def _count_tokens(content: str) -> int:
    return len(_TOKEN_COUNT_RE.findall(content))


class DocumentParseService:
    def __init__(
        self,
        session: Session,
        storage: ObjectStorageAdapter | None = None,
        parsers: list[ParserAdapter] | None = None,
        *,
        adaptive_chunking: bool = False,
        chunking_service: ChunkingService | None = None,
        chunking_policy: ChunkPolicy | None = None,
    ) -> None:
        self.session = session
        self.storage = storage or get_storage_adapter()
        self.parsers = parsers or get_parser_chain()
        # Task 16 owns Settings/feature-flag wiring.  Until then this is
        # deliberately constructor-injected so ingestion never reads env vars.
        self.adaptive_chunking = adaptive_chunking
        if adaptive_chunking:
            if chunking_service is None:
                counter = LocalTokenCounter()
                chunking_service = ChunkingService(counter)
                chunking_policy = chunking_policy or ChunkPolicy(
                    tokenizer_name=counter.name,
                    tokenizer_version=counter.version,
                )
            if chunking_policy is None:
                raise ValueError(
                    "adaptive chunking requires an injected ChunkPolicy "
                    "when ChunkingService is injected"
                )
            self.chunking_service = chunking_service
            self.chunking_policy = chunking_policy
        else:
            self.chunking_service = chunking_service
            self.chunking_policy = chunking_policy

    def parse_import_job(self, job_id: str) -> ImportJob:
        job = self.session.get(ImportJob, job_id)
        if job is None:
            raise ValueError("Import job does not exist")
        # Serialize all collection decisions for this document.  PostgreSQL
        # emits SELECT .. FOR UPDATE; SQLite safely ignores the clause for its
        # single-writer test/development semantics.  The lock lasts through the
        # final commit, then a waiting worker re-reads the active collection.
        document = self.session.scalar(
            select(Document)
            .where(Document.id == job.document_id)
            .with_for_update()
        )
        if document is None:
            raise ValueError("Import job document does not exist")

        # Idempotency: a duplicate delivery of an already-finished job is a no-op.
        if job.status == ImportJobStatus.COMPLETED.value:
            self.session.commit()
            return job
        # Adaptive collections are versioned by their boundary-affecting
        # configuration.  Retry delivery before QA completes must not replace
        # a complete collection with identical parent/child rows, create a new
        # artifact, or invalidate QaPair -> CHILD references.
        if self._has_current_adaptive_collection(document.id):
            self.session.commit()  # release the document lock before returning
            self._run_artifact_gc_best_effort(document.id, job.id)
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
            job.status = ImportJobStatus.RUNNING.value
            job.stage = "CHUNKING"
            job.progress = max(job.progress, 30)
            task_run.stage = "CHUNKING"
            self.session.commit()

            chunk_count, artifact_key, replaced_object_keys = self._replace_parse_outputs(
                job, document, parsed.markdown, parsed.blocks
            )

            document.parser_name = parsed.parser_name
            document.parser_version = parsed.parser_version
            document.page_count = parsed.page_count
            document.chunk_count = chunk_count
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
            # Storage deletion happens only after the DB commit that makes the
            # replacement artifact live, so rollback can never orphan an
            # ACTIVE DB reference.  Failures are retained as GC markers.
            self._run_artifact_gc_best_effort(
                document.id,
                job.id,
                replaced_object_keys,
                current_object_key=artifact_key,
            )
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
    ) -> tuple[int, str, tuple[str, ...]]:
        """Write a new collection and return old object keys for post-commit GC."""
        artifact_key = f"artifacts/{document.id}/parsed/{uuid4().hex}.md"
        data = markdown.encode("utf-8")
        self.storage.put_object(artifact_key, data)
        previous_keys = tuple(
            self.session.scalars(
                select(ParseArtifact.object_key).where(
                    ParseArtifact.document_id == document.id,
                    ParseArtifact.job_id == job.id,
                    ParseArtifact.artifact_type == "PARSED_MARKDOWN",
                )
            ).all()
        )
        try:
            with self.session.begin_nested():
                self.session.execute(
                    delete(ParseArtifact).where(
                        ParseArtifact.document_id == document.id,
                        ParseArtifact.job_id == job.id,
                        ParseArtifact.artifact_type == "PARSED_MARKDOWN",
                    )
                )
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
                if self.adaptive_chunking:
                    chunk_count = self._write_adaptive_chunks(job, document, blocks)
                else:
                    chunk_count = self._write_legacy_chunks(job, document, blocks)
        except Exception:
            # The savepoint restores previous artifact/chunk rows.  Clean the
            # new immutable object best-effort; if deletion is unavailable, a
            # durable marker is committed with the failed task for later GC.
            self._delete_failed_attempt_object(job, document, artifact_key)
            raise
        return chunk_count, artifact_key, previous_keys

    def _delete_failed_attempt_object(
        self,
        job: ImportJob,
        document: Document,
        object_key: str,
    ) -> None:
        try:
            self.storage.delete_object(object_key)
        except Exception:
            logger.warning(
                "parse attempt object cleanup deferred document_id=%s key_hash=%s",
                document.id,
                hashlib.sha256(object_key.encode("utf-8")).hexdigest(),
                exc_info=True,
            )
            self._queue_artifact_gc_marker(
                self.session,
                job,
                document,
                object_key,
                reason="PARSE_ATTEMPT_ROLLBACK",
            )

    def _queue_artifact_gc_marker(
        self,
        session: Session,
        job: ImportJob,
        document: Document,
        object_key: str,
        *,
        reason: str,
    ) -> None:
        existing = session.scalar(
            select(ParseArtifact.id).where(
                ParseArtifact.document_id == document.id,
                ParseArtifact.job_id == job.id,
                ParseArtifact.artifact_type == "ORPHANED_OBJECT_GC_PENDING",
                ParseArtifact.object_key == object_key,
            )
        )
        if existing is None:
            session.add(
                ParseArtifact(
                    tenant_id=job.tenant_id,
                    document_id=document.id,
                    job_id=job.id,
                    artifact_type="ORPHANED_OBJECT_GC_PENDING",
                    object_key=object_key,
                    content_hash=None,
                    artifact_metadata={"gcReason": reason},
                )
            )

    def _run_artifact_gc_best_effort(
        self,
        document_id: str,
        job_id: str,
        replaced_object_keys: tuple[str, ...] = (),
        *,
        current_object_key: str | None = None,
    ) -> None:
        """Isolate post-commit storage/GC failures from parse outcome state."""
        try:
            self._reclaim_orphaned_artifacts(
                document_id,
                job_id,
                replaced_object_keys,
                current_object_key=current_object_key,
            )
        except Exception:
            # The primary parse transaction already committed.  A storage or
            # GC-marker failure must never transition its Job, Document, or
            # TaskRun back to FAILED; a periodic GC retry can recover later.
            logger.warning(
                "post-commit artifact GC deferred document_id=%s key_count=%s",
                document_id,
                len(replaced_object_keys),
                exc_info=True,
            )

    def _reclaim_orphaned_artifacts(
        self,
        document_id: str,
        job_id: str,
        replaced_object_keys: tuple[str, ...] = (),
        *,
        current_object_key: str | None = None,
    ) -> None:
        """Best-effort GC in an independent, rollback-safe DB session."""
        gc_session = Session(bind=self.session.get_bind())
        try:
            markers = list(
                gc_session.scalars(
                    select(ParseArtifact).where(
                        ParseArtifact.document_id == document_id,
                        ParseArtifact.job_id == job_id,
                        ParseArtifact.artifact_type == "ORPHANED_OBJECT_GC_PENDING",
                    )
                ).all()
            )
            marker_by_key = {marker.object_key: marker for marker in markers}
            keys = set(replaced_object_keys) | set(marker_by_key)
            changed = False
            for object_key in keys:
                if object_key == current_object_key:
                    continue
                is_referenced = gc_session.scalar(
                    select(ParseArtifact.id).where(
                        ParseArtifact.object_key == object_key,
                        ParseArtifact.artifact_type == "PARSED_MARKDOWN",
                    )
                )
                if is_referenced is not None:
                    continue
                try:
                    self.storage.delete_object(object_key)
                except Exception:
                    logger.warning(
                        "artifact GC deferred document_id=%s key_hash=%s",
                        document_id,
                        hashlib.sha256(object_key.encode("utf-8")).hexdigest(),
                        exc_info=True,
                    )
                    marker = marker_by_key.get(object_key)
                    if marker is None:
                        job = gc_session.get(ImportJob, job_id)
                        document = gc_session.get(Document, document_id)
                        if job is not None and document is not None:
                            self._queue_artifact_gc_marker(
                                gc_session,
                                job,
                                document,
                                object_key,
                                reason="REPLACED_ARTIFACT",
                            )
                            changed = True
                else:
                    marker = marker_by_key.get(object_key)
                    if marker is not None:
                        gc_session.delete(marker)
                        changed = True
            if changed:
                gc_session.commit()
            else:
                gc_session.rollback()
        except Exception:
            gc_session.rollback()
            raise
        finally:
            gc_session.close()

    def _has_current_adaptive_collection(self, document_id: str) -> bool:
        """Return true only for a complete, homogeneous active collection."""
        if not self.adaptive_chunking or self.chunking_policy is None:
            return False
        active = list(
            self.session.scalars(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.deleted_at.is_(None),
                    DocumentChunk.status == "ACTIVE",
                )
            ).all()
        )
        if not active:
            return False
        policy = self.chunking_policy
        if any(
            row.chunker_name != policy.name
            or row.chunker_version != policy.version
            or row.chunker_config_hash != policy.config_hash
            for row in active
        ):
            return False
        parent_ids = {row.id for row in active if row.chunk_level == "PARENT"}
        children = [row for row in active if row.chunk_level == "CHILD"]
        return bool(children) and all(
            child.parent_chunk_id in parent_ids for child in children
        )

    def _write_legacy_chunks(self, job: ImportJob, document: Document, blocks) -> int:
        self.session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_id == document.id)
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
        return len(blocks)

    def _write_adaptive_chunks(self, job: ImportJob, document: Document, blocks) -> int:
        if self.chunking_service is None or self.chunking_policy is None:
            raise RuntimeError("adaptive chunking requires service and policy")
        atomic_blocks = tuple(
            AtomicBlock(
                index=block.index,
                content=block.content,
                block_type=block.block_type,
                source_locator=block.source_locator or {"blockIndex": block.index},
                page_no=block.page_no,
                title_path=tuple(block.title_path),
                structural_id=block.structural_id,
                parent_structural_id=block.parent_structural_id,
                metadata=block.metadata,
            )
            for block in blocks
        )
        started = perf_counter()
        result = self.chunking_service.chunk(
            atomic_blocks,
            self.chunking_policy,
            document_title=document.title,
        )
        log_chunking_observability(
            tenant_id=job.tenant_id,
            document_id=document.id,
            job_id=job.id,
            parser_name=document.parser_name or "unknown",
            parser_version=document.parser_version or "unknown",
            policy=self.chunking_policy,
            result=result,
            duration_seconds=perf_counter() - started,
        )
        parent_by_local_id: dict[str, DocumentChunk] = {}
        staged: list[DocumentChunk] = []
        for normalized in result.parents:
            row = self._chunk_row(job, document, normalized, parent_chunk_id=None)
            self.session.add(row)
            staged.append(row)
            parent_by_local_id[normalized.local_id] = row
        # Parents need durable PKs before children can carry the self-FK.
        self.session.flush()
        for normalized in result.children:
            parent = parent_by_local_id[normalized.parent_local_id]
            row = self._chunk_row(job, document, normalized, parent_chunk_id=parent.id)
            self.session.add(row)
            staged.append(row)
        self.session.flush()

        # The switch is deliberately the final DB operation in this savepoint:
        # readers observe the old ACTIVE set until the complete replacement is
        # present, and never a partial parent/child collection.
        self.session.query(DocumentChunk).filter(
            DocumentChunk.document_id == document.id,
            DocumentChunk.status == "ACTIVE",
        ).update({DocumentChunk.status: "SUPERSEDED"}, synchronize_session=False)
        for row in staged:
            row.status = "ACTIVE"
        return len(result.children)

    def _chunk_row(self, job, document, normalized, *, parent_chunk_id: str | None) -> DocumentChunk:
        metadata = to_json_value(normalized.metadata)
        return DocumentChunk(
            tenant_id=job.tenant_id,
            document_id=document.id,
            job_id=job.id,
            chunk_index=normalized.chunk_index,
            title_path=list(normalized.title_path),
            content=normalized.content,
            page_no=normalized.page_start,
            token_count=normalized.token_count,
            source_locator=to_json_value(normalized.source_locators[0]),
            status="STAGING",
            block_type=normalized.block_type.value,
            chunk_level=normalized.level.value,
            parent_chunk_id=parent_chunk_id,
            page_start=normalized.page_start,
            page_end=normalized.page_end,
            source_locators=[to_json_value(item) for item in normalized.source_locators],
            atomic_block_indexes=list(normalized.atomic_block_indexes),
            content_hash=normalized.content_hash,
            chunker_name=self.chunking_policy.name,
            chunker_version=self.chunking_policy.version,
            chunker_config_hash=self.chunking_policy.config_hash,
            search_text=normalized.content,
            chunk_metadata=metadata,
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
        job.stage = job.stage or "PARSING"
        job.error_code = code
        job.error_message = message
        task_run.stage = job.stage
        task_run.status = "FAILED"
        task_run.error = {
            "code": code,
            "message": message,
            "retryable": retryable,
            "failedAt": datetime.now(UTC).isoformat(),
        }
        self.session.commit()
