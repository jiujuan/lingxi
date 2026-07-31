"""Resumable, atomic maintenance backfill for adaptive chunk collections.

The service deliberately derives its source from the currently active CHILD
collection.  It never deletes the old collection: a complete replacement is
first staged and verified in a savepoint, then the ACTIVE switch is performed
as the final operation of that same transaction.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
import logging
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.app.models.document import Document, DocumentStatus
from server.app.models.logs import TaskRun
from server.app.models.qa_pair import DocumentChunk
from server.app.services.chunking import (
    AtomicBlock,
    BlockType,
    ChunkPolicy,
    ChunkingService,
    NormalizedChunk,
    to_json_value,
)

logger = logging.getLogger(__name__)


class BackfillError(RuntimeError):
    """A structured backfill failure suitable for Celery retry decisions."""

    def __init__(self, code: str, message: str, *, retryable: bool = True) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class BackfillOptions:
    tenant_id: str | None = None
    document_id: str | None = None
    from_chunker_version: str | None = None
    to_chunker_version: str | None = None
    batch_size: int = 100
    resume_after: str | None = None
    dry_run: bool = False
    rebuild_qa: bool = False
    rebuild_embedding: bool = False
    execution_id: str | None = None
    operator_id: str | None = None
    audit_source: str | None = None
    audit_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.batch_size, int) or isinstance(self.batch_size, bool):
            raise ValueError("batch_size must be an integer")
        if self.batch_size <= 0:
            raise ValueError("batch_size must be greater than zero")
        for name in (
            "tenant_id",
            "document_id",
            "from_chunker_version",
            "to_chunker_version",
            "resume_after",
            "execution_id",
            "operator_id",
            "audit_source",
            "audit_reason",
        ):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ValueError(f"{name} must be a non-empty string when supplied")


@dataclass(frozen=True)
class BackfillResult:
    targeted: int = 0
    rebuilt: int = 0
    reused: int = 0
    next_cursor: str | None = None
    dry_run: bool = False

    def as_dict(self) -> dict:
        return {
            "targeted": self.targeted,
            "rebuilt": self.rebuilt,
            "reused": self.reused,
            "nextCursor": self.next_cursor,
            "dryRun": self.dry_run,
        }


QaRebuilder = Callable[[Document, bool], None]


class ChunkBackfillService:
    """Build versioned adaptive collections from the current active Children.

    ``qa_rebuilder`` is an explicit callback so the maintenance state
    transition is testable and the service does not silently invoke a model
    provider. The callback runs only after the replacement collection commit;
    when embedding is requested it must arrange the existing QA -> embedding
    task sequence rather than enqueueing embedding before QA succeeds.
    """

    def __init__(
        self,
        session: Session,
        *,
        chunking_service: ChunkingService,
        chunking_policy: ChunkPolicy,
        qa_rebuilder: QaRebuilder | None = None,
    ) -> None:
        self.session = session
        self.chunking_service = chunking_service
        self.chunking_policy = chunking_policy
        self.qa_rebuilder = qa_rebuilder

    def count_targets(
        self, options: BackfillOptions, *, task_type: str = "backfill_adaptive_chunks"
    ) -> int:
        """Return the exact number of eligible Documents without mutating DB state."""
        effective_options = self._effective_options(options, task_type)
        return sum(
            1
            for document in self._documents(effective_options, limit=None)
            if self._needs_work(document, effective_options)
        )

    def backfill(
        self,
        options: BackfillOptions,
        *,
        task_type: str = "backfill_adaptive_chunks",
        queue_name: str = "maintenance",
    ) -> BackfillResult:
        self._recover_scheduled_follow_ups(options, task_type)
        options = self._effective_options(options, task_type)
        documents = self._documents(options, limit=options.batch_size)
        targeted = rebuilt = reused = 0
        next_cursor: str | None = options.resume_after
        completed_cursor: str | None = options.resume_after

        for document in documents:
            next_cursor = document.id
            if not self._matches_source_version(document, options):
                if not options.dry_run:
                    task_run = self._start_task_run(document, task_type, queue_name, options)
                    self._finish_task_run(
                        task_run,
                        document.id,
                        options,
                        stage="SKIPPED",
                    )
                    completed_cursor = document.id
                continue
            targeted += 1
            if options.dry_run:
                continue
            task_run = self._start_task_run(document, task_type, queue_name, options)
            try:
                self._validate_follow_up_options(options)
                if self._has_target_collection(document.id, self._target_policy(options)):
                    reused += 1
                else:
                    self._rebuild_document(document.id, options)
                    rebuilt += 1
                self._schedule_follow_ups(document, options)
                self._mark_follow_ups_scheduled(task_run, document.id, options)
            except BackfillError as exc:
                self._fail_task_run(
                    document,
                    task_run,
                    task_type,
                    queue_name,
                    exc,
                    completed_cursor,
                    options,
                )
                self._log_failure(document, options, exc, completed_cursor)
                raise
            except Exception as exc:
                error = BackfillError(
                    "CHUNK_BACKFILL_INTERNAL_ERROR",
                    "adaptive chunk backfill failed",
                    retryable=True,
                )
                self._fail_task_run(
                    document,
                    task_run,
                    task_type,
                    queue_name,
                    error,
                    completed_cursor,
                    options,
                )
                self._log_failure(document, options, error, completed_cursor)
                raise error from exc
            else:
                self._finish_task_run(task_run, document.id, options)
                completed_cursor = document.id

        return BackfillResult(
            targeted=targeted,
            rebuilt=rebuilt,
            reused=reused,
            next_cursor=next_cursor,
            dry_run=options.dry_run,
        )

    def _effective_options(self, options: BackfillOptions, task_type: str) -> BackfillOptions:
        if options.execution_id is None:
            return options
        durable_cursor = self._durable_cursor(options.execution_id, task_type)
        cursors = [cursor for cursor in (options.resume_after, durable_cursor) if cursor]
        cursor = max(cursors) if cursors else None
        return replace(options, resume_after=cursor) if cursor else options

    def _durable_cursor(self, execution_id: str, task_type: str) -> str | None:
        runs = self.session.scalars(
            select(TaskRun)
            .where(
                TaskRun.request_id == execution_id,
                TaskRun.task_type == task_type,
                TaskRun.resource_type == "DOCUMENT",
                TaskRun.status == "SUCCESS",
            )
            .order_by(TaskRun.created_at.desc(), TaskRun.id.desc())
        ).all()
        cursors: list[str] = []
        for run in runs:
            metadata = run.error if isinstance(run.error, dict) else {}
            cursor = metadata.get("resumeAfter")
            if isinstance(cursor, str) and cursor:
                cursors.append(cursor)
        return max(cursors) if cursors else None

    def _recover_scheduled_follow_ups(
        self, options: BackfillOptions, task_type: str
    ) -> None:
        """Close crash-interrupted runs after their QA dispatch has committed.

        Follow-up dispatch is an external side effect.  Once the callback
        returns successfully we commit a dedicated checkpoint before writing
        the normal SUCCESS cursor.  If the worker dies after that checkpoint,
        a retry of the same execution can safely advance the existing run
        without re-enqueueing QA/embedding work.
        """
        if options.execution_id is None:
            return

        target_config_hash = self._target_policy(options).config_hash
        runs = self.session.scalars(
            select(TaskRun)
            .where(
                TaskRun.request_id == options.execution_id,
                TaskRun.task_type == task_type,
                TaskRun.resource_type == "DOCUMENT",
                TaskRun.status == "RUNNING",
                TaskRun.stage == "FOLLOW_UPS_SCHEDULED",
            )
            .with_for_update()
        ).all()
        recovered = False
        for run in runs:
            metadata = run.error if isinstance(run.error, dict) else {}
            follow_up = metadata.get("followUp")
            if (
                not isinstance(follow_up, dict)
                or follow_up.get("qa") != "SCHEDULED"
                or follow_up.get("targetConfigHash") != target_config_hash
                or follow_up.get("rebuildEmbedding") != options.rebuild_embedding
                or metadata.get("resumeAfter") != run.resource_id
            ):
                continue
            run.status = "SUCCESS"
            run.stage = "READY"
            run.error = self._run_metadata(options, run.resource_id)
            recovered = True
        if recovered:
            self.session.commit()

    def _documents(self, options: BackfillOptions, *, limit: int | None) -> list[Document]:
        statement = select(Document).where(Document.status != DocumentStatus.DELETED)
        if options.tenant_id:
            statement = statement.where(Document.tenant_id == options.tenant_id)
        if options.document_id:
            statement = statement.where(Document.id == options.document_id)
        if options.resume_after:
            statement = statement.where(Document.id > options.resume_after)
        statement = statement.order_by(Document.id)
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.session.scalars(statement).all())

    def _target_policy(self, options: BackfillOptions) -> ChunkPolicy:
        if options.to_chunker_version is None:
            return self.chunking_policy
        return replace(self.chunking_policy, version=options.to_chunker_version)

    def _active_children(self, document_id: str) -> list[DocumentChunk]:
        return list(
            self.session.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.status == "ACTIVE",
                    DocumentChunk.chunk_level == "CHILD",
                )
                .order_by(DocumentChunk.chunk_index, DocumentChunk.id)
            ).all()
        )

    def _matches_source_version(self, document: Document, options: BackfillOptions) -> bool:
        children = self._active_children(document.id)
        if not children:
            return False
        return options.from_chunker_version is None or all(
            child.chunker_version == options.from_chunker_version for child in children
        )

    def _needs_work(self, document: Document, options: BackfillOptions) -> bool:
        return self._matches_source_version(document, options) and not self._has_target_collection(
            document.id, self._target_policy(options)
        )

    def _has_target_collection(self, document_id: str, policy: ChunkPolicy) -> bool:
        active = list(
            self.session.scalars(
                select(DocumentChunk).where(
                    DocumentChunk.document_id == document_id,
                    DocumentChunk.status == "ACTIVE",
                )
            ).all()
        )
        if not active:
            return False
        if any(
            row.chunker_name != policy.name
            or row.chunker_version != policy.version
            or row.chunker_config_hash != policy.config_hash
            for row in active
        ):
            return False
        parents = {row.id for row in active if row.chunk_level == "PARENT"}
        children = [row for row in active if row.chunk_level == "CHILD"]
        return bool(parents and children and all(child.parent_chunk_id in parents for child in children))

    def _rebuild_document(self, document_id: str, options: BackfillOptions) -> None:
        document = self.session.scalar(
            select(Document).where(Document.id == document_id).with_for_update()
        )
        if document is None or document.status == DocumentStatus.DELETED:
            raise BackfillError("CHUNK_BACKFILL_DOCUMENT_MISSING", "document is unavailable", retryable=False)
        policy = self._target_policy(options)
        sources = self._active_children(document.id)
        if not sources:
            raise BackfillError("CHUNK_BACKFILL_SOURCE_MISSING", "active source children are missing", retryable=False)
        if options.from_chunker_version and not all(
            row.chunker_version == options.from_chunker_version for row in sources
        ):
            return
        if self._has_target_collection(document.id, policy):
            return

        try:
            with self.session.begin_nested():
                result = self.chunking_service.chunk(
                    self._to_atomic_blocks(sources), policy, document_title=document.title
                )
                staged = self._stage_collection(document, sources, result.parents, result.children, policy)
                self.session.flush()
                self._verify_collection(staged, policy)

                self.session.query(DocumentChunk).filter(
                    DocumentChunk.document_id == document.id,
                    DocumentChunk.status == "ACTIVE",
                ).update({DocumentChunk.status: "SUPERSEDED"}, synchronize_session=False)
                for row in staged:
                    row.status = "ACTIVE"
                self.session.flush()

            self.session.commit()
        except BackfillError:
            raise
        except Exception as exc:
            raise BackfillError(
                "CHUNK_BACKFILL_BUILD_FAILED",
                "adaptive collection build failed",
                retryable=True,
            ) from exc

        logger.info(
            "adaptive chunk backfill completed tenant_id=%s document_id=%s target_config_hash=%s child_count=%d",
            document.tenant_id,
            document.id,
            policy.config_hash,
            len([row for row in staged if row.chunk_level == "CHILD"]),
        )

    @staticmethod
    def _validate_follow_up_options(options: BackfillOptions) -> None:
        if options.rebuild_embedding and not options.rebuild_qa:
            raise BackfillError(
                "CHUNK_BACKFILL_EMBEDDING_REQUIRES_QA",
                "embedding rebuild requires QA rebuild for the new chunk generation",
                retryable=False,
            )

    def _schedule_follow_ups(self, document: Document, options: BackfillOptions) -> None:
        if not options.rebuild_qa:
            return
        if self.qa_rebuilder is None:
            raise BackfillError(
                "CHUNK_BACKFILL_QA_SCHEDULER_MISSING",
                "QA rebuild scheduler is unavailable",
                retryable=True,
            )
        try:
            self.qa_rebuilder(document, options.rebuild_embedding)
        except BackfillError:
            raise
        except Exception as exc:
            raise BackfillError(
                "CHUNK_BACKFILL_QA_SCHEDULE_FAILED",
                "QA rebuild scheduling failed",
                retryable=True,
            ) from exc

    def _mark_follow_ups_scheduled(
        self,
        task_run: TaskRun,
        cursor: str,
        options: BackfillOptions,
    ) -> None:
        """Persist a recovery checkpoint after the broker callback succeeds."""
        if not options.rebuild_qa:
            return
        persisted_run = self.session.get(TaskRun, task_run.id)
        if persisted_run is None:
            raise BackfillError(
                "CHUNK_BACKFILL_TASK_RUN_MISSING",
                "backfill TaskRun is unavailable",
                retryable=True,
            )
        persisted_run.stage = "FOLLOW_UPS_SCHEDULED"
        persisted_run.error = {
            **self._run_metadata(options, cursor),
            "followUp": {
                "qa": "SCHEDULED",
                "rebuildEmbedding": options.rebuild_embedding,
                "targetConfigHash": self._target_policy(options).config_hash,
            },
        }
        self.session.commit()

    def _to_atomic_blocks(self, sources: Sequence[DocumentChunk]) -> tuple[AtomicBlock, ...]:
        blocks: list[AtomicBlock] = []
        for index, source in enumerate(sources):
            try:
                block_type = BlockType(source.block_type)
            except ValueError:
                block_type = BlockType.TEXT
            blocks.append(
                AtomicBlock(
                    index=index,
                    content=source.content,
                    block_type=block_type,
                    source_locator=source.source_locator or {"chunkId": source.id},
                    page_no=source.page_no,
                    title_path=tuple(source.title_path or ()),
                    metadata=source.chunk_metadata or {},
                )
            )
        return tuple(blocks)

    def _stage_collection(
        self,
        document: Document,
        sources: Sequence[DocumentChunk],
        parents: Sequence[NormalizedChunk],
        children: Sequence[NormalizedChunk],
        policy: ChunkPolicy,
    ) -> list[DocumentChunk]:
        parent_by_local_id: dict[str, DocumentChunk] = {}
        staged: list[DocumentChunk] = []
        source_job_id = sources[0].job_id
        for normalized in parents:
            row = self._chunk_row(document, source_job_id, normalized, policy, parent_chunk_id=None)
            self.session.add(row)
            staged.append(row)
            parent_by_local_id[normalized.local_id] = row
        self.session.flush()
        for normalized in children:
            parent = parent_by_local_id.get(normalized.parent_local_id)
            if parent is None:
                raise BackfillError("CHUNK_BACKFILL_INVALID_HIERARCHY", "child has no staged parent", retryable=False)
            row = self._chunk_row(document, source_job_id, normalized, policy, parent_chunk_id=parent.id)
            self.session.add(row)
            staged.append(row)
        return staged

    def _chunk_row(
        self,
        document: Document,
        job_id: str | None,
        normalized: NormalizedChunk,
        policy: ChunkPolicy,
        *,
        parent_chunk_id: str | None,
    ) -> DocumentChunk:
        return DocumentChunk(
            tenant_id=document.tenant_id,
            document_id=document.id,
            job_id=job_id,
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
            source_locators=[to_json_value(locator) for locator in normalized.source_locators],
            atomic_block_indexes=list(normalized.atomic_block_indexes),
            content_hash=normalized.content_hash,
            chunker_name=policy.name,
            chunker_version=policy.version,
            chunker_config_hash=policy.config_hash,
            search_text=normalized.content,
            chunk_metadata=to_json_value(normalized.metadata),
        )

    def _verify_collection(self, staged: Sequence[DocumentChunk], policy: ChunkPolicy) -> None:
        parents = [row for row in staged if row.chunk_level == "PARENT"]
        children = [row for row in staged if row.chunk_level == "CHILD"]
        parent_ids = {row.id for row in parents}
        if not parents or not children or not all(child.parent_chunk_id in parent_ids for child in children):
            raise BackfillError("CHUNK_BACKFILL_VERIFICATION_FAILED", "staged collection is incomplete", retryable=False)
        if any(
            row.status != "STAGING"
            or row.chunker_name != policy.name
            or row.chunker_version != policy.version
            or row.chunker_config_hash != policy.config_hash
            for row in staged
        ):
            raise BackfillError("CHUNK_BACKFILL_VERIFICATION_FAILED", "staged collection metadata is invalid", retryable=False)

    def _start_task_run(
        self,
        document: Document,
        task_type: str,
        queue_name: str,
        options: BackfillOptions,
    ) -> TaskRun:
        run = TaskRun(
            tenant_id=document.tenant_id,
            task_type=task_type,
            queue_name=queue_name,
            resource_type="DOCUMENT",
            resource_id=document.id,
            stage="CHUNKING",
            status="RUNNING",
            error=None,
            request_id=options.execution_id,
        )
        self.session.add(run)
        # Persist the run before mutating chunks. A subsequent collection
        # rollback cannot erase the only durable failure/retry record.
        self.session.commit()
        return run

    def _finish_task_run(
        self,
        task_run: TaskRun,
        cursor: str,
        options: BackfillOptions,
        *,
        stage: str = "READY",
    ) -> None:
        task_run = self.session.get(TaskRun, task_run.id)
        if task_run is None:
            raise BackfillError(
                "CHUNK_BACKFILL_TASK_RUN_MISSING",
                "backfill TaskRun is unavailable",
                retryable=True,
            )
        task_run.status = "SUCCESS"
        task_run.stage = stage
        task_run.error = self._run_metadata(options, cursor)
        self.session.commit()

    def _fail_task_run(
        self,
        document: Document,
        task_run: TaskRun,
        task_type: str,
        queue_name: str,
        error: BackfillError,
        cursor: str | None,
        options: BackfillOptions,
    ) -> None:
        # Never mutate the pre-rollback ORM instance. Re-load the independently
        # committed run (or recreate it if that durable insert itself failed).
        self.session.rollback()
        persisted_run = self.session.get(TaskRun, task_run.id)
        if persisted_run is None:
            persisted_run = TaskRun(
                tenant_id=document.tenant_id,
                task_type=task_type,
                queue_name=queue_name,
                resource_type="DOCUMENT",
                resource_id=document.id,
                request_id=options.execution_id,
            )
            self.session.add(persisted_run)
        # The maintenance record deliberately has no document content, prompt,
        # or source locator. IDs and safe progress metadata are enough to
        # resume without leaking document body into operational logs.
        metadata = self._run_metadata(options, cursor)
        persisted_run.status = "FAILED"
        persisted_run.stage = "FAILED_RETRYABLE" if error.retryable else "FAILED_FINAL"
        persisted_run.error = {
            "code": error.code,
            "retryable": error.retryable,
            **metadata,
        }
        self.session.commit()

    @staticmethod
    def _run_metadata(options: BackfillOptions, cursor: str | None) -> dict:
        values = {
            "executionId": options.execution_id,
            "source": options.audit_source,
            "operatorId": options.operator_id,
            "reason": options.audit_reason,
        }
        return {
            "resumeAfter": cursor,
            **{key: value for key, value in values.items() if value is not None},
        }

    def _log_failure(
        self,
        document: Document,
        options: BackfillOptions,
        error: BackfillError,
        cursor: str | None,
    ) -> None:
        logger.error(
            "adaptive chunk backfill failed code=%s tenant_id=%s document_id=%s "
            "target_config_hash=%s retryable=%s resume_after=%s",
            error.code,
            document.tenant_id,
            document.id,
            self._target_policy(options).config_hash,
            error.retryable,
            cursor,
        )
