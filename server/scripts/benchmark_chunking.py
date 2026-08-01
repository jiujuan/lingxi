"""Offline adaptive-chunking capacity and retrieval regression benchmark.

This hermetic benchmark measures CPU work after parser output is available and
the real local ``RetrievalService.retrieve()`` request path. It uses a frozen
representative parser-block corpus and temporary in-memory SQLite databases;
it never contacts an external database, worker, parser, object store, model
provider, or vector index. The retrieval timing is a local regression gate,
not production PostgreSQL, vector-index, provider, or network latency
evidence. Task 19's live end-to-end evaluator remains required release
evidence for those environments.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from time import perf_counter, process_time
from typing import Any
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from server.app.core.retrieval_config import RetrievalConfig, get_retrieval_config  # noqa: E402
from server.app.core.permissions import AccessContext  # noqa: E402
from server.app.services.chunking.contracts import (  # noqa: E402
    AtomicBlock,
    BlockType,
    ChunkingResult,
    NormalizedChunk,
    to_json_value,
)
from server.app.services.chunking.normalization import normalize_text  # noqa: E402
from server.app.services.chunking.policy import ChunkPolicy  # noqa: E402
from server.app.services.chunking.service import ChunkingService  # noqa: E402
from server.app.services.chunking.tokenizer import LocalTokenCounter  # noqa: E402
from server.app.db.base import Base  # noqa: E402
from server.app.models.document import (  # noqa: E402
    Document,
    DocumentAccessRule,
    DocumentAccessSubjectType,
    DocumentStatus,
)
from server.app.models.import_job import ImportJob, ImportJobStatus  # noqa: E402
from server.app.models.qa_pair import DocumentChunk, QaPair  # noqa: E402
from server.app.services.document_parse_service import DocumentParseService  # noqa: E402
from server.app.services.retrieval_service import RetrievalService  # noqa: E402
from server.app.services.seed_service import seed_identity_data  # noqa: E402


_SCHEMA_VERSION = "adaptive-chunking-benchmark/v1"
_CORPUS_SCHEMA_VERSION = "adaptive-chunking-benchmark-corpus/v1"
_FLOAT_VECTOR_BYTES = 4
_VECTOR_DIMENSIONS = 1536
_VECTOR_INDEX_OVERHEAD_BYTES = 64
_NFR004_RETRIEVAL_P95_MULTIPLIER = 2.00
# Accumulate enough work that one coarse Windows CPU-clock tick is below the
# threshold margin.  This changes sampling stability, not any NFR threshold.
_CPU_MIN_SAMPLE_MS = 500.0
_FIXED_PERSIST_IDS = {"tenantId": "benchmark-tenant", "documentId": "benchmark-document", "jobId": "benchmark-job"}


class BenchmarkInputError(ValueError):
    """The supplied fixed corpus cannot produce a trustworthy benchmark."""


@dataclass(frozen=True)
class CorpusSummary:
    source_document_count: int
    atomic_block_count: int
    page_count: int
    total_bytes: int
    sha256: str


@dataclass(frozen=True)
class LegacyPersistWork:
    """Actual legacy row construction plus shared parser-artifact preparation."""

    persisted_bytes: int
    parse_artifact_count: int
    legacy_chunk_row_count: int
    flat_child_contents: tuple[str, ...]
    legacy_rows: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class _PersistedChunkRow:
    """Detached values copied before the temporary ORM transaction rolls back."""

    chunk_index: int
    title_path: list[Any]
    content: str
    page_no: int | None
    token_count: int
    source_locator: dict[str, Any]
    status: str
    block_type: str | None
    chunk_level: str | None
    parent_chunk_id: str | None
    page_start: int | None
    page_end: int | None
    source_locators: list[Any]
    atomic_block_indexes: list[int]
    content_hash: str | None
    search_text: str | None
    chunk_metadata: dict[str, Any]


class _MemoryArtifactStorage:
    """Hermetic storage boundary for production parse-output persistence."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def put_object(self, object_key: str, data: bytes) -> None:
        self._objects[object_key] = data

    def delete_object(self, object_key: str) -> None:
        self._objects.pop(object_key, None)

    def clear(self) -> None:
        self._objects.clear()


@dataclass
class _PersistenceHarness:
    """Temporary local dependencies for production parse/persist methods."""

    session: Session
    storage: _MemoryArtifactStorage
    job: ImportJob
    document: Document
    legacy_service: DocumentParseService
    adaptive_service: DocumentParseService
    markdown: str

    def close(self) -> None:
        self.session.close()


@dataclass
class _RetrievalHarness:
    """Hermetic, authorized fixture for timing production retrieval paths."""

    session: Session
    context: AccessContext
    queries: tuple[str, ...]

    def close(self) -> None:
        self.session.close()


class _DeterministicReranker:
    """Avoid provider calls and missed-question writes during local timing."""

    def rerank(self, _question: str, candidates: list) -> list:
        for candidate in candidates:
            candidate.rerank_score = max(candidate.fused_score, 2.0)
        return candidates


@dataclass(frozen=True)
class AcceptanceOutcome:
    acceptance: dict[str, bool]
    failure_reasons: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {"acceptance": self.acceptance, "failureReasons": self.failure_reasons}


def _percentile(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise BenchmarkInputError("benchmark timing samples must not be empty")
    if not 0 <= percentile <= 100:
        raise ValueError("percentile must be between 0 and 100")
    ordered = sorted(float(value) for value in values)
    if any(not math.isfinite(value) or value < 0 for value in ordered):
        raise BenchmarkInputError("benchmark timing samples must be finite and non-negative")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * percentile / 100
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _timing_summary(samples_ms: Sequence[float]) -> dict[str, float]:
    return {"p50Ms": round(_percentile(samples_ms, 50), 6), "p95Ms": round(_percentile(samples_ms, 95), 6)}


def _serialized_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _corpus_hash(corpus: str | Path) -> str:
    corpus_path = Path(corpus)
    digest = hashlib.sha256()
    for path in sorted(item for item in corpus_path.rglob("*") if item.is_file()):
        digest.update(path.relative_to(corpus_path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _manifest_block_type(value: Any, *, path: Path) -> BlockType:
    try:
        return BlockType(value)
    except (TypeError, ValueError) as exc:
        raise BenchmarkInputError(f"invalid blockType in {path}: {value!r}") from exc


def load_corpus_blocks(corpus: str | Path) -> tuple[tuple[AtomicBlock, ...], CorpusSummary]:
    """Load the frozen v1 representative corpus as parser-equivalent blocks."""

    corpus_path = Path(corpus)
    manifest_path = corpus_path / "manifest.json"
    if not corpus_path.is_dir():
        raise BenchmarkInputError(f"benchmark corpus directory does not exist: {corpus_path}")
    if not manifest_path.is_file():
        raise BenchmarkInputError(f"benchmark corpus requires manifest.json: {manifest_path}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BenchmarkInputError(f"benchmark corpus manifest is invalid: {manifest_path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != _CORPUS_SCHEMA_VERSION:
        raise BenchmarkInputError(f"benchmark corpus schema must be {_CORPUS_SCHEMA_VERSION}")
    documents = manifest.get("documents")
    if not isinstance(documents, list) or not documents:
        raise BenchmarkInputError("benchmark corpus must contain at least one document")

    blocks: list[AtomicBlock] = []
    pages: set[tuple[str, int]] = set()
    source_identities: set[str] = set()
    for document in documents:
        if not isinstance(document, dict):
            raise BenchmarkInputError("benchmark corpus documents must be objects")
        source_identity = document.get("sourceIdentity")
        title = document.get("title")
        document_blocks = document.get("blocks")
        if not isinstance(source_identity, str) or not source_identity.strip():
            raise BenchmarkInputError("benchmark corpus document sourceIdentity must be non-empty")
        if source_identity in source_identities:
            raise BenchmarkInputError(f"benchmark corpus sourceIdentity is duplicated: {source_identity}")
        if not isinstance(title, str) or not title.strip():
            raise BenchmarkInputError("benchmark corpus document title must be non-empty")
        if not isinstance(document_blocks, list) or not document_blocks:
            raise BenchmarkInputError(f"benchmark corpus document has no blocks: {source_identity}")
        source_identities.add(source_identity)
        for raw_block in document_blocks:
            if not isinstance(raw_block, dict):
                raise BenchmarkInputError(f"benchmark corpus block must be an object: {source_identity}")
            content = raw_block.get("content")
            page = raw_block.get("page")
            title_path = raw_block.get("titlePath")
            structural_id = raw_block.get("structuralId")
            metadata = raw_block.get("metadata", {})
            if not isinstance(content, str) or not content.strip():
                raise BenchmarkInputError(f"benchmark corpus block content is empty: {source_identity}")
            if not isinstance(page, int) or isinstance(page, bool) or page <= 0:
                raise BenchmarkInputError(f"benchmark corpus page must be positive: {source_identity}")
            if not isinstance(title_path, list) or not all(isinstance(item, str) and item for item in title_path):
                raise BenchmarkInputError(f"benchmark corpus titlePath must be non-empty strings: {source_identity}")
            if structural_id is not None and not isinstance(structural_id, str):
                raise BenchmarkInputError(f"benchmark corpus structuralId must be a string: {source_identity}")
            try:
                blocks.append(
                    AtomicBlock(
                        index=len(blocks),
                        content=content,
                        block_type=_manifest_block_type(raw_block.get("blockType"), path=manifest_path),
                        source_locator={"sourceIdentity": source_identity, "blockIndex": len(blocks), "page": page},
                        page_no=page,
                        title_path=tuple(title_path),
                        structural_id=structural_id,
                        metadata=metadata,
                    )
                )
            except ValueError as exc:
                raise BenchmarkInputError(f"benchmark corpus block is invalid: {source_identity}") from exc
            pages.add((source_identity, page))
    summary = CorpusSummary(
        source_document_count=len(source_identities),
        atomic_block_count=len(blocks),
        page_count=len(pages),
        total_bytes=sum(path.stat().st_size for path in corpus_path.rglob("*") if path.is_file()),
        sha256=_corpus_hash(corpus_path),
    )
    return tuple(blocks), summary


def _parser_artifact_payload(blocks: Sequence[AtomicBlock]) -> dict[str, Any]:
    """The shared parser-output artifact preparation both complete envelopes perform."""

    return {
        "artifactType": "PARSED_BLOCKS",
        "blocks": [
            {
                "index": block.index,
                "content": block.content,
                "blockType": block.block_type.value,
                "sourceLocator": to_json_value(block.source_locator),
                "pageNo": block.page_no,
                "titlePath": list(block.title_path),
                "structuralId": block.structural_id,
                "parentStructuralId": block.parent_structural_id,
                "metadata": to_json_value(block.metadata),
            }
            for block in blocks
        ],
    }


def _legacy_row_payload(row: _PersistedChunkRow) -> dict[str, Any]:
    """Serialize a row created by ``DocumentParseService._write_legacy_chunks``."""

    return {
        **_FIXED_PERSIST_IDS,
        "chunkIndex": row.chunk_index,
        "titlePath": list(row.title_path),
        "content": row.content,
        "pageNo": row.page_no,
        "tokenCount": row.token_count,
        "sourceLocator": to_json_value(row.source_locator),
        "status": row.status,
    }


def _benchmark_markdown(blocks: Sequence[AtomicBlock]) -> str:
    return "\n\n".join(block.content for block in blocks)


def _production_parser_blocks(
    blocks: Sequence[AtomicBlock],
) -> tuple[SimpleNamespace, ...]:
    """Adapt immutable benchmark contracts to the parser-service row boundary."""

    return tuple(
        SimpleNamespace(
            index=block.index,
            content=block.content,
            block_type=block.block_type,
            source_locator=to_json_value(block.source_locator),
            page_no=block.page_no,
            title_path=list(block.title_path),
            structural_id=block.structural_id,
            parent_structural_id=block.parent_structural_id,
            metadata=to_json_value(block.metadata),
        )
        for block in blocks
    )


def _new_persistence_harness(
    service: ChunkingService,
    policy: ChunkPolicy,
    blocks: Sequence[AtomicBlock],
) -> _PersistenceHarness:
    """Build an in-memory SQLAlchemy unit used by both production write paths."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    document = Document(
        id=_FIXED_PERSIST_IDS["documentId"],
        tenant_id=_FIXED_PERSIST_IDS["tenantId"],
        title="adaptive chunking benchmark",
        file_name="benchmark.md",
        file_type="MARKDOWN",
        mime_type="text/markdown",
        file_size=len(_benchmark_markdown(blocks).encode("utf-8")),
        object_key="benchmark/input.md",
        checksum="benchmark",
        status=DocumentStatus.PARSING,
    )
    job = ImportJob(
        id=_FIXED_PERSIST_IDS["jobId"],
        tenant_id=_FIXED_PERSIST_IDS["tenantId"],
        document_id=document.id,
        status=ImportJobStatus.RUNNING.value,
        stage="PARSING",
    )
    session.add_all((document, job))
    session.commit()
    storage = _MemoryArtifactStorage()
    # Parsers are never called by this post-parser benchmark.  A truthy
    # sentinel prevents constructor fallback to configured external parsers.
    parsers = [object()]
    return _PersistenceHarness(
        session=session,
        storage=storage,
        job=job,
        document=document,
        legacy_service=DocumentParseService(
            session,
            storage=storage,
            parsers=parsers,
            adaptive_chunking=False,
        ),
        adaptive_service=DocumentParseService(
            session,
            storage=storage,
            parsers=parsers,
            adaptive_chunking=True,
            chunking_service=service,
            chunking_policy=policy,
        ),
        markdown=_benchmark_markdown(blocks),
    )


def _new_retrieval_harness() -> _RetrievalHarness:
    """Seed production models for real QA-only and Hybrid request timing."""

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    identity = seed_identity_data(session)
    tenant_id = identity["tenant"].id
    evidence = (
        (
            "refund",
            "退款审批需要主管确认",
            "退款需要谁审批",
            [1.0, 0.0, 0.0, 0.0],
        ),
        (
            "invoice",
            "发票退款需要先红冲发票",
            "发票退款前要做什么",
            [0.0, 1.0, 0.0, 0.0],
        ),
    )
    for index, (topic, content, query, vector) in enumerate(evidence):
        document = Document(
            tenant_id=tenant_id,
            title=f"{topic} benchmark",
            file_name=f"{topic}.md",
            file_type="MARKDOWN",
            mime_type="text/markdown",
            file_size=len(content.encode("utf-8")),
            object_key=f"benchmark/{topic}.md",
            checksum=f"benchmark-{topic}",
            status=DocumentStatus.READY,
        )
        session.add(document)
        session.flush()
        session.add(
            DocumentAccessRule(
                tenant_id=tenant_id,
                document_id=document.id,
                subject_type=DocumentAccessSubjectType.ALL_AUTHENTICATED,
                subject_id=None,
            )
        )
        chunk = DocumentChunk(
            tenant_id=tenant_id,
            document_id=document.id,
            chunk_index=index,
            title_path=[topic],
            content=content,
            token_count=4,
            source_locator={"benchmark": topic},
            source_locators=[{"benchmark": topic}],
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            embedding=vector,
            search_text=content,
            status="ACTIVE",
            chunk_level="CHILD",
        )
        session.add(chunk)
        session.flush()
        session.add(
            QaPair(
                tenant_id=tenant_id,
                document_id=document.id,
                chunk_id=chunk.id,
                pair_index=index,
                question=query,
                answer=content,
                quote=content,
                question_embedding=vector,
                search_text=query,
                status="ACTIVE",
            )
        )
    session.commit()
    return _RetrievalHarness(
        session=session,
        context=AccessContext(
            tenant_id=tenant_id,
            user_id=identity["users"]["employee"].id,
            department_id=identity["departments"]["support"].id,
            role_ids=[identity["roles"]["employee"].id],
            permissions={"DOCUMENT_READ"},
            role_codes={"EMPLOYEE"},
        ),
        queries=tuple(query for _topic, _content, query, _vector in evidence),
    )


def _retrieval_service(
    harness: _RetrievalHarness, *, hybrid: bool
) -> RetrievalService:
    """Return a real service with only remote retrieval dependencies replaced."""

    service = RetrievalService(
        harness.session,
        config=replace(get_retrieval_config(), final_top_k=5),
        reranker=_DeterministicReranker(),
        hybrid_chunk_retrieval_enabled=hybrid,
        parent_context_enabled=False,
    )
    service._embed_query = lambda _tenant_id, _question: [1.0, 0.0, 0.0, 0.0]
    return service


def _measure_retrieval_ms(
    service: RetrievalService, harness: _RetrievalHarness
) -> float:
    """Measure one fixed real request sequence with a wall clock."""

    started = perf_counter()
    for query in harness.queries:
        service.retrieve(harness.context, query)
    return (perf_counter() - started) * 1000


def _persisted_chunk_snapshot(row: DocumentChunk) -> _PersistedChunkRow:
    """Copy ORM values while the row is live, before rolling back its envelope."""

    return _PersistedChunkRow(
        chunk_index=row.chunk_index,
        title_path=list(row.title_path or []),
        content=row.content,
        page_no=row.page_no,
        token_count=row.token_count,
        source_locator=to_json_value(row.source_locator or {}),
        status=row.status,
        block_type=row.block_type,
        chunk_level=row.chunk_level,
        parent_chunk_id=row.parent_chunk_id,
        page_start=row.page_start,
        page_end=row.page_end,
        source_locators=[
            to_json_value(item) for item in (row.source_locators or [])
        ],
        atomic_block_indexes=list(row.atomic_block_indexes or []),
        content_hash=row.content_hash,
        search_text=row.search_text,
        chunk_metadata=to_json_value(row.chunk_metadata or {}),
    )


def _write_production_envelope(
    harness: _PersistenceHarness,
    blocks: Sequence[AtomicBlock],
    *,
    adaptive: bool,
) -> tuple[_PersistedChunkRow, ...]:
    """Execute and roll back the real production parse-output write envelope."""

    service = harness.adaptive_service if adaptive else harness.legacy_service
    # SQLite does not issue a physical BEGIN for a read-only ORM transaction.
    # `_replace_parse_outputs` creates a nested SAVEPOINT; without a real
    # outer BEGIN, releasing that SAVEPOINT commits an iteration and pollutes
    # the next warmup sample.  Force the outer transaction before the
    # production method opens its savepoint, then roll it back below.
    connection = harness.session.connection()
    connection.exec_driver_sql("BEGIN")
    try:
        service._replace_parse_outputs(
            harness.job,
            harness.document,
            harness.markdown,
            _production_parser_blocks(blocks),
        )
        # Legacy rows are pending after `_write_legacy_chunks`; the production
        # outer transaction flushes them at its persistence boundary.  Adaptive
        # has already flushed parent and child rows, so this is a no-op there.
        harness.session.flush()
        return tuple(
            _persisted_chunk_snapshot(row)
            for row in harness.session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == harness.document.id)
                .order_by(DocumentChunk.chunk_level, DocumentChunk.chunk_index)
            ).all()
        )
    finally:
        harness.session.rollback()
        harness.storage.clear()


def _legacy_parse_persist(
    blocks: Iterable[AtomicBlock],
    *,
    harness: _PersistenceHarness | None = None,
) -> LegacyPersistWork:
    """Execute the production legacy raw-row/token-count persistence method."""

    source_blocks = tuple(blocks)
    counter = LocalTokenCounter()
    policy = ChunkPolicy(tokenizer_name=counter.name, tokenizer_version=counter.version)
    owned_harness = harness is None
    active_harness = harness or _new_persistence_harness(
        ChunkingService(counter), policy, source_blocks
    )
    try:
        rows = _write_production_envelope(active_harness, source_blocks, adaptive=False)
        payloads = tuple(_legacy_row_payload(row) for row in rows)
        persisted_bytes = _serialized_size(_parser_artifact_payload(source_blocks))
        persisted_bytes += sum(_serialized_size(row) for row in payloads)
        return LegacyPersistWork(
            persisted_bytes=persisted_bytes,
            parse_artifact_count=1,
            legacy_chunk_row_count=len(payloads),
            flat_child_contents=tuple(row.content for row in rows),
            legacy_rows=payloads,
        )
    finally:
        if owned_harness:
            active_harness.close()


def _adaptive_chunk_row_payload(chunk: NormalizedChunk, policy: ChunkPolicy) -> dict[str, Any]:
    """Mirror adaptive ``DocumentParseService._chunk_row`` persistence fields."""

    return {
        **_FIXED_PERSIST_IDS,
        "chunkIndex": chunk.chunk_index,
        "titlePath": list(chunk.title_path),
        "content": chunk.content,
        "pageNo": chunk.page_start,
        "tokenCount": chunk.token_count,
        "sourceLocator": to_json_value(chunk.source_locators[0]),
        "status": "STAGING",
        "blockType": chunk.block_type.value,
        "chunkLevel": chunk.level.value,
        "parentLocalId": chunk.parent_local_id,
        "pageStart": chunk.page_start,
        "pageEnd": chunk.page_end,
        "sourceLocators": [to_json_value(item) for item in chunk.source_locators],
        "atomicBlockIndexes": list(chunk.atomic_block_indexes),
        "contentHash": chunk.content_hash,
        "chunkerName": policy.name,
        "chunkerVersion": policy.version,
        "chunkerConfigHash": policy.config_hash,
        "searchText": chunk.content,
        "chunkMetadata": to_json_value(chunk.metadata),
    }


def _persisted_adaptive_row_payload(
    row: _PersistedChunkRow,
    policy: ChunkPolicy,
) -> dict[str, Any]:
    """Serialize a row created by the production adaptive persistence method."""

    return {
        **_FIXED_PERSIST_IDS,
        "chunkIndex": row.chunk_index,
        "titlePath": list(row.title_path),
        "content": row.content,
        "pageNo": row.page_no,
        "tokenCount": row.token_count,
        "sourceLocator": to_json_value(row.source_locator),
        "status": row.status,
        "blockType": row.block_type,
        "chunkLevel": row.chunk_level,
        "parentLocalId": row.parent_chunk_id,
        "pageStart": row.page_start,
        "pageEnd": row.page_end,
        "sourceLocators": [to_json_value(item) for item in row.source_locators],
        "atomicBlockIndexes": list(row.atomic_block_indexes),
        "contentHash": row.content_hash,
        "chunkerName": policy.name,
        "chunkerVersion": policy.version,
        "chunkerConfigHash": policy.config_hash,
        "searchText": row.search_text,
        "chunkMetadata": to_json_value(row.chunk_metadata),
    }


def _adaptive_parse_persist(
    service: ChunkingService,
    policy: ChunkPolicy,
    blocks: Sequence[AtomicBlock],
    *,
    harness: _PersistenceHarness | None = None,
) -> tuple[tuple[str, ...], int]:
    """Execute the production adaptive parse-output persistence method."""

    owned_harness = harness is None
    active_harness = harness or _new_persistence_harness(service, policy, blocks)
    try:
        rows = _write_production_envelope(active_harness, blocks, adaptive=True)
        payloads = tuple(
            _persisted_adaptive_row_payload(row, policy) for row in rows
        )
        persisted_bytes = _serialized_size(_parser_artifact_payload(blocks))
        persisted_bytes += sum(_serialized_size(payload) for payload in payloads)
        return (
            tuple(
                sorted(
                    row.content_hash
                    for row in rows
                    if row.chunk_level == "CHILD"
                )
            ),
            persisted_bytes,
        )
    finally:
        if owned_harness:
            active_harness.close()


def _query_terms(query: str) -> tuple[str, ...]:
    normalized = normalize_text(query).casefold()
    return tuple(token for token in normalized.replace("-", " ").split() if token)


def _score_rows(query: str, rows: Iterable[tuple[str, str]]) -> list[tuple[str, int]]:
    terms = _query_terms(query)
    ranked = [(identity, sum(content.casefold().count(term) for term in terms)) for identity, content in rows]
    return sorted(ranked, key=lambda item: (-item[1], item[0]))


def _build_post_top_k_fusion_proxy_inputs(
    result: ChunkingResult,
    blocks: Sequence[AtomicBlock],
    queries: Sequence[str],
    config: RetrievalConfig,
) -> tuple[tuple[tuple[tuple[str, int], ...], ...], tuple[tuple[tuple[str, int], ...], ...]]:
    """Construct actual configured channel caps before timing only post-Top-K fusion."""

    qa_rows = [
        (f"{block.source_locator['sourceIdentity']}:{block.index}", block.content)
        for block in blocks
    ]
    child_rows = [(chunk.local_id, chunk.content) for chunk in result.children]
    qa_only: list[tuple[tuple[str, int], ...]] = []
    hybrid: list[tuple[tuple[str, int], ...]] = []
    for query in queries:
        qa_ranked = _score_rows(query, qa_rows)
        child_ranked = _score_rows(query, child_rows)
        qa_only.append((tuple(qa_ranked[: config.vector_top_k]), tuple(qa_ranked[: config.text_top_k])))
        hybrid.append(
            (
                tuple(qa_ranked[: config.hybrid_qa_vector_top_k]),
                tuple(child_ranked[: config.hybrid_chunk_vector_top_k]),
                tuple(qa_ranked[: config.hybrid_qa_text_top_k]),
                tuple(child_ranked[: config.hybrid_chunk_text_top_k]),
            )
        )
    return tuple(qa_only), tuple(hybrid)


def _rrf_rank(channels: Iterable[Sequence[tuple[str, int]]]) -> list[tuple[str, float]]:
    scores: dict[str, float] = {}
    for channel in channels:
        for rank, (identity, _score) in enumerate(channel, 1):
            scores[identity] = scores.get(identity, 0.0) + 1.0 / (60 + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def _qa_only_post_top_k_fusion_cpu_proxy(ranked_rows: Sequence[Sequence[Sequence[tuple[str, int]]]]) -> None:
    for channels in ranked_rows:
        _rrf_rank(channels)


def _hybrid_post_top_k_fusion_cpu_proxy(ranked_rows: Sequence[Sequence[Sequence[tuple[str, int]]]]) -> None:
    for channels in ranked_rows:
        _rrf_rank(channels)


def _measure_cpu_ms(operation) -> float:
    """Return a stable CPU sample despite coarse Windows process timers."""

    iterations = 1
    while True:
        started = process_time()
        for _ in range(iterations):
            operation()
        elapsed_ms = (process_time() - started) * 1000
        if elapsed_ms >= _CPU_MIN_SAMPLE_MS:
            return elapsed_ms / iterations
        iterations *= 2


def _index_estimate(result: ChunkingResult, persisted_bytes: int) -> dict[str, int]:
    embedding_count = len(result.children)
    vector_bytes = embedding_count * _VECTOR_DIMENSIONS * _FLOAT_VECTOR_BYTES
    vector_index_bytes = embedding_count * _VECTOR_INDEX_OVERHEAD_BYTES
    return {"rowPayloadBytes": persisted_bytes, "embeddingVectorBytes": vector_bytes, "vectorIndexOverheadBytes": vector_index_bytes, "totalBytes": persisted_bytes + vector_bytes + vector_index_bytes}


def _finite_nonnegative(value: float) -> bool:
    return math.isfinite(value) and value >= 0


def evaluate_acceptance(
    *,
    baseline_parse_p95_ms: float,
    candidate_chunk_p95_ms: float,
    baseline_proxy_p95_ms: float,
    candidate_proxy_p95_ms: float,
    baseline_retrieval_p95_ms: float,
    candidate_retrieval_p95_ms: float,
    child_hash_sets: list[tuple[str, ...]],
) -> dict[str, Any]:
    """Evaluate every gate independently and retain every applicable reason."""

    reasons: list[str] = []
    if not child_hash_sets or any(not hashes for hashes in child_hash_sets):
        deterministic = False
        reasons.append("determinism failed: Child hash sets must be non-empty")
    elif len(set(child_hash_sets)) != 1:
        deterministic = False
        reasons.append("determinism failed: Child hash sets differ between runs")
    else:
        deterministic = True

    parse_values_valid = _finite_nonnegative(baseline_parse_p95_ms) and _finite_nonnegative(candidate_chunk_p95_ms)
    if not parse_values_valid:
        nfr003 = False
        reasons.append("NFR-003 failed: parse/persist CPU P95 values must be finite and non-negative")
    elif baseline_parse_p95_ms <= 0:
        nfr003 = False
        reasons.append("NFR-003 failed: legacy parse/persist CPU P95 baseline must be positive")
    elif candidate_chunk_p95_ms > baseline_parse_p95_ms * 1.20:
        nfr003 = False
        reasons.append("NFR-003 failed: adaptive parse/persist CPU P95 exceeds legacy parse/persist P95 × 1.20")
    else:
        nfr003 = True

    proxy_values_valid = _finite_nonnegative(baseline_proxy_p95_ms) and _finite_nonnegative(candidate_proxy_p95_ms)
    if not proxy_values_valid:
        proxy = False
        reasons.append("post-Top-K fusion CPU proxy failed: P95 values must be finite and non-negative")
    elif baseline_proxy_p95_ms <= 0:
        proxy = False
        reasons.append("post-Top-K fusion CPU proxy failed: QA-only P95 baseline must be positive")
    elif candidate_proxy_p95_ms > baseline_proxy_p95_ms * 1.30:
        proxy = False
        reasons.append("post-Top-K fusion CPU proxy failed: hybrid P95 exceeds QA-only P95 × 1.30")
    else:
        proxy = True

    retrieval_values_valid = _finite_nonnegative(
        baseline_retrieval_p95_ms
    ) and _finite_nonnegative(candidate_retrieval_p95_ms)
    if not retrieval_values_valid:
        nfr004 = False
        reasons.append(
            "NFR-004 failed: retrieval P95 values must be finite and non-negative"
        )
    elif baseline_retrieval_p95_ms <= 0:
        nfr004 = False
        reasons.append(
            "NFR-004 failed: QA-only retrieval P95 baseline must be positive"
        )
    elif (
        candidate_retrieval_p95_ms
        > baseline_retrieval_p95_ms * _NFR004_RETRIEVAL_P95_MULTIPLIER
    ):
        nfr004 = False
        reasons.append(
            "NFR-004 failed: hybrid retrieval P95 exceeds QA-only retrieval P95 x 2.00"
        )
    else:
        nfr004 = True

    return AcceptanceOutcome(
        acceptance={
            "determinismChildHashes": deterministic,
            "nfr003ChunkingCpu": nfr003,
            "postTopKFusionCpuProxy": proxy,
            "nfr004Retrieval": nfr004,
        },
        failure_reasons=reasons,
    ).as_dict()


def _stats_summary(result: ChunkingResult) -> dict[str, int]:
    values = asdict(result.stats)
    return {"mergeCount": values["merge_count"], "splitCount": values["split_count"], "oversizedCount": values["oversized_count"], "overlapChildCount": sum(1 for child in result.children if child.overlap_prefix_tokens > 0)}


def run_benchmark(corpus: str | Path, repeat: int = 5) -> dict[str, Any]:
    """Run complete local envelopes and return a report even if gates fail."""

    if not isinstance(repeat, int) or isinstance(repeat, bool) or repeat <= 0:
        raise BenchmarkInputError("repeat must be a positive integer")
    blocks, corpus_summary = load_corpus_blocks(corpus)
    counter = LocalTokenCounter()
    policy = ChunkPolicy(tokenizer_name=counter.name, tokenizer_version=counter.version)
    service = ChunkingService(counter)
    config = get_retrieval_config()
    queries = tuple(sorted({block.title_path[0] for block in blocks}))
    legacy_samples: list[float] = []
    adaptive_samples: list[float] = []
    qa_proxy_samples: list[float] = []
    hybrid_proxy_samples: list[float] = []
    qa_retrieval_samples: list[float] = []
    hybrid_retrieval_samples: list[float] = []
    child_hash_sets: list[tuple[str, ...]] = []
    final_result: ChunkingResult | None = None
    final_persisted_bytes = 0
    final_legacy_work: LegacyPersistWork | None = None

    harness = _new_persistence_harness(service, policy, blocks)
    try:
        for _ in range(repeat):
            legacy_work: LegacyPersistWork | None = None

            def legacy_operation() -> None:
                nonlocal legacy_work
                legacy_work = _legacy_parse_persist(blocks, harness=harness)

            legacy_samples.append(_measure_cpu_ms(legacy_operation))
            adaptive_child_hashes: tuple[str, ...] | None = None
            persisted_bytes = 0

            def adaptive_operation() -> None:
                nonlocal adaptive_child_hashes, persisted_bytes
                adaptive_child_hashes, persisted_bytes = _adaptive_parse_persist(
                    service,
                    policy,
                    blocks,
                    harness=harness,
                )

            adaptive_samples.append(_measure_cpu_ms(adaptive_operation))
            if adaptive_child_hashes is None or legacy_work is None:
                raise AssertionError("benchmark operation must produce a result")
            # Result construction is intentionally outside the timed production
            # persistence envelope: it supplies reporting/proxy fixtures only.
            result = service.chunk(
                blocks,
                policy,
                document_title="adaptive chunking benchmark",
            )
            if adaptive_child_hashes != tuple(
                sorted(child.content_hash for child in result.children)
            ):
                raise BenchmarkInputError(
                    "production adaptive persistence emitted unexpected child hashes"
                )
            child_hash_sets.append(adaptive_child_hashes)
            qa_only_inputs, hybrid_inputs = _build_post_top_k_fusion_proxy_inputs(result, blocks, queries, config)
            qa_proxy_samples.append(_measure_cpu_ms(lambda: _qa_only_post_top_k_fusion_cpu_proxy(qa_only_inputs)))
            hybrid_proxy_samples.append(_measure_cpu_ms(lambda: _hybrid_post_top_k_fusion_cpu_proxy(hybrid_inputs)))
            final_result = result
            final_persisted_bytes = persisted_bytes
            final_legacy_work = legacy_work
    finally:
        harness.close()

    if final_result is None or final_legacy_work is None:
        raise AssertionError("positive repeat count must produce a benchmark result")
    legacy_timing = _timing_summary(legacy_samples)
    adaptive_timing = _timing_summary(adaptive_samples)
    qa_proxy_timing = _timing_summary(qa_proxy_samples)
    hybrid_proxy_timing = _timing_summary(hybrid_proxy_samples)
    retrieval_harness = _new_retrieval_harness()
    try:
        qa_retrieval_service = _retrieval_service(retrieval_harness, hybrid=False)
        hybrid_retrieval_service = _retrieval_service(retrieval_harness, hybrid=True)
        # Warm tokenizer/import paths before collecting the fixed samples.
        _measure_retrieval_ms(qa_retrieval_service, retrieval_harness)
        _measure_retrieval_ms(hybrid_retrieval_service, retrieval_harness)
        for _ in range(repeat):
            qa_retrieval_samples.append(
                _measure_retrieval_ms(qa_retrieval_service, retrieval_harness)
            )
            hybrid_retrieval_samples.append(
                _measure_retrieval_ms(hybrid_retrieval_service, retrieval_harness)
            )
    finally:
        retrieval_harness.close()
    qa_retrieval_timing = _timing_summary(qa_retrieval_samples)
    hybrid_retrieval_timing = _timing_summary(hybrid_retrieval_samples)
    acceptance_outcome = evaluate_acceptance(
        baseline_parse_p95_ms=legacy_timing["p95Ms"],
        candidate_chunk_p95_ms=adaptive_timing["p95Ms"],
        baseline_proxy_p95_ms=qa_proxy_timing["p95Ms"],
        candidate_proxy_p95_ms=hybrid_proxy_timing["p95Ms"],
        baseline_retrieval_p95_ms=qa_retrieval_timing["p95Ms"],
        candidate_retrieval_p95_ms=hybrid_retrieval_timing["p95Ms"],
        child_hash_sets=child_hash_sets,
    )
    megabytes = corpus_summary.total_bytes / (1024 * 1024)
    adaptive_timing.update({"perMbMs": round(adaptive_timing["p95Ms"] / megabytes, 6) if megabytes else 0.0, "perPageMs": round(adaptive_timing["p95Ms"] / corpus_summary.page_count, 6)})
    report = {
        "schemaVersion": _SCHEMA_VERSION,
        "measurement": {
            "clock": "process_time",
            "retrievalClock": "perf_counter",
            "unit": "milliseconds",
            "externalParserIncluded": False,
            "networkIncluded": False,
            "retrievalEnvironment": {
                "database": "in-memory SQLite",
                "embedding": "deterministic local",
                "reranker": "deterministic local",
                "parentHydrationIncluded": False,
                "remoteLatencyIncluded": False,
            },
        },
        "corpus": {"path": str(Path(corpus)), "sourceDocumentCount": corpus_summary.source_document_count, "atomicBlockCount": corpus_summary.atomic_block_count, "pageCount": corpus_summary.page_count, "bytes": corpus_summary.total_bytes, "sha256": corpus_summary.sha256},
        "determinism": {"repeatCount": repeat, "childHashSets": [list(item) for item in child_hash_sets], "childHashSetStable": len(set(child_hash_sets)) == 1},
        "counts": {"parentCount": len(final_result.parents), "childCount": len(final_result.children), "embeddingCount": len(final_result.children)},
        "stats": _stats_summary(final_result),
        "baselineWork": {"parseArtifactCount": final_legacy_work.parse_artifact_count, "legacyChunkRowCount": final_legacy_work.legacy_chunk_row_count},
        "indexEstimate": _index_estimate(final_result, final_persisted_bytes),
        "timings": {
            "legacyParsePersist": legacy_timing,
            "adaptiveParsePersist": adaptive_timing,
            "qaOnlyPostTopKFusionCpuProxy": qa_proxy_timing,
            "hybridPostTopKFusionCpuProxy": hybrid_proxy_timing,
            "qaOnlyRetrieval": qa_retrieval_timing,
            "hybridRetrieval": hybrid_retrieval_timing,
        },
        "acceptance": acceptance_outcome["acceptance"],
        "acceptanceFailureReasons": acceptance_outcome["failureReasons"],
    }
    validate_benchmark_report(report)
    return report


def validate_benchmark_report(report: dict[str, Any]) -> None:
    """Reject malformed reports before the CLI persists success or gate failure evidence."""

    if not isinstance(report, dict) or report.get("schemaVersion") != _SCHEMA_VERSION:
        raise BenchmarkInputError("benchmark report schemaVersion is invalid")
    required_sections = {"measurement", "corpus", "determinism", "counts", "stats", "baselineWork", "indexEstimate", "timings", "acceptance", "acceptanceFailureReasons"}
    missing = sorted(required_sections - set(report))
    if missing:
        raise BenchmarkInputError(f"benchmark report missing sections: {', '.join(missing)}")
    if not isinstance(report["timings"], dict) or set(report["timings"]) != {
        "legacyParsePersist",
        "adaptiveParsePersist",
        "qaOnlyPostTopKFusionCpuProxy",
        "hybridPostTopKFusionCpuProxy",
        "qaOnlyRetrieval",
        "hybridRetrieval",
    }:
        raise BenchmarkInputError("benchmark report timings schema is invalid")
    for timing_name, timing in report["timings"].items():
        if not isinstance(timing, dict):
            raise BenchmarkInputError(
                f"benchmark report timing {timing_name} schema is invalid"
            )
        expected_keys = {"p50Ms", "p95Ms"}
        if timing_name == "adaptiveParsePersist":
            expected_keys |= {"perMbMs", "perPageMs"}
        if set(timing) != expected_keys or not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and _finite_nonnegative(float(value))
            for value in timing.values()
        ):
            raise BenchmarkInputError(
                f"benchmark report timing {timing_name} schema is invalid"
            )
    measurement = report["measurement"]
    expected_measurement = {
        "clock": "process_time",
        "retrievalClock": "perf_counter",
        "unit": "milliseconds",
        "externalParserIncluded": False,
        "networkIncluded": False,
        "retrievalEnvironment": {
            "database": "in-memory SQLite",
            "embedding": "deterministic local",
            "reranker": "deterministic local",
            "parentHydrationIncluded": False,
            "remoteLatencyIncluded": False,
        },
    }
    if measurement != expected_measurement:
        raise BenchmarkInputError("benchmark report measurement schema is invalid")
    required_acceptance = {
        "determinismChildHashes",
        "nfr003ChunkingCpu",
        "postTopKFusionCpuProxy",
        "nfr004Retrieval",
    }
    if set(report["acceptance"]) != required_acceptance or not all(isinstance(value, bool) for value in report["acceptance"].values()):
        raise BenchmarkInputError("benchmark report acceptance schema is invalid")
    if not isinstance(report["acceptanceFailureReasons"], list) or not all(isinstance(reason, str) and reason for reason in report["acceptanceFailureReasons"]):
        raise BenchmarkInputError("benchmark report acceptanceFailureReasons schema is invalid")
    failure_prefixes = {
        "determinismChildHashes": "determinism failed:",
        "nfr003ChunkingCpu": "NFR-003 failed:",
        "postTopKFusionCpuProxy": "post-Top-K fusion CPU proxy failed:",
        "nfr004Retrieval": "NFR-004 failed:",
    }
    for gate, prefix in failure_prefixes.items():
        has_reason = any(reason.startswith(prefix) for reason in report["acceptanceFailureReasons"])
        if report["acceptance"][gate] is False and not has_reason:
            raise BenchmarkInputError(
                f"benchmark report must explain failed {prefix.removesuffix(':')}"
            )
        if report["acceptance"][gate] is True and has_reason:
            raise BenchmarkInputError(
                f"benchmark report cannot report a passing {prefix.removesuffix(':')}"
            )
    if any(
        not any(reason.startswith(prefix) for prefix in failure_prefixes.values())
        for reason in report["acceptanceFailureReasons"]
    ):
        raise BenchmarkInputError(
            "benchmark report acceptanceFailureReasons contains an unknown gate"
        )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path)
    parser.add_argument("--repeat", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        report = run_benchmark(args.corpus, repeat=args.repeat)
        validate_benchmark_report(report)
    except BenchmarkInputError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote benchmark report to {args.output} (Child={report['counts']['childCount']}, P95={report['timings']['adaptiveParsePersist']['p95Ms']}ms)")
    if report["acceptanceFailureReasons"]:
        print("\n".join(report["acceptanceFailureReasons"]), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
