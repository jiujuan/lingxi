from __future__ import annotations

import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).parents[2]
BENCHMARK_CORPUS = (
    REPOSITORY_ROOT
    / "server"
    / "tests"
    / "fixtures"
    / "chunking_eval"
    / "benchmark_corpus"
)


def test_offline_benchmark_reports_representative_hierarchy_and_proxy_metrics():
    from server.scripts.benchmark_chunking import run_benchmark

    report = run_benchmark(BENCHMARK_CORPUS, repeat=2)

    assert report["schemaVersion"] == "adaptive-chunking-benchmark/v1"
    assert report["corpus"]["sourceDocumentCount"] == 2
    assert report["corpus"]["atomicBlockCount"] == 30
    assert report["corpus"]["pageCount"] == 6
    assert report["corpus"]["bytes"] > 10_000
    assert len(report["corpus"]["sha256"]) == 64
    assert report["determinism"]["repeatCount"] == 2
    assert report["determinism"]["childHashSetStable"] is True
    assert len({tuple(item) for item in report["determinism"]["childHashSets"]}) == 1
    assert report["stats"]["mergeCount"] > 0
    assert report["stats"]["splitCount"] > 0
    assert report["stats"]["overlapChildCount"] > 0
    assert report["counts"]["parentCount"] > 0
    assert report["counts"]["childCount"] > report["counts"]["parentCount"]
    assert (
        report["counts"]["parentCount"] + report["counts"]["childCount"]
        > report["corpus"]["atomicBlockCount"]
    )
    assert report["counts"]["embeddingCount"] == report["counts"]["childCount"]
    assert report["indexEstimate"]["totalBytes"] > 0
    for stage in (
        "legacyParsePersist",
        "adaptiveParsePersist",
        "qaOnlyPostTopKFusionCpuProxy",
        "hybridPostTopKFusionCpuProxy",
        "qaOnlyRetrieval",
        "hybridRetrieval",
    ):
        assert report["timings"][stage]["p50Ms"] >= 0
        assert report["timings"][stage]["p95Ms"] >= 0
    assert report["timings"]["adaptiveParsePersist"]["perMbMs"] >= 0
    assert report["timings"]["adaptiveParsePersist"]["perPageMs"] >= 0
    assert report["acceptance"]["determinismChildHashes"] is True
    assert report["acceptance"]["nfr003ChunkingCpu"] is True
    assert report["acceptance"]["postTopKFusionCpuProxy"] is True
    assert isinstance(report["acceptance"]["nfr004Retrieval"], bool)
    nfr004_reasons = [
        reason
        for reason in report["acceptanceFailureReasons"]
        if reason.startswith("NFR-004 failed:")
    ]
    assert bool(nfr004_reasons) is not report["acceptance"]["nfr004Retrieval"]


def test_offline_benchmark_reports_real_retrieval_timings_and_nfr004(monkeypatch):
    import server.scripts.benchmark_chunking as benchmark
    from server.app.services.retrieval_service import RetrievalService

    calls = 0
    original_retrieve = RetrievalService.retrieve

    def trace_retrieve(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original_retrieve(self, *args, **kwargs)

    monkeypatch.setattr(RetrievalService, "retrieve", trace_retrieve)

    report = benchmark.run_benchmark(BENCHMARK_CORPUS, repeat=1)

    assert calls > 0
    assert report["measurement"]["retrievalEnvironment"] == {
        "database": "in-memory SQLite",
        "embedding": "deterministic local",
        "reranker": "deterministic local",
        "parentHydrationIncluded": False,
        "remoteLatencyIncluded": False,
    }
    assert report["timings"]["qaOnlyRetrieval"]["p50Ms"] >= 0
    assert report["timings"]["hybridRetrieval"]["p95Ms"] >= 0
    assert isinstance(report["acceptance"]["nfr004Retrieval"], bool)


def test_acceptance_reports_nfr004_failure_independently():
    from server.scripts.benchmark_chunking import evaluate_acceptance

    outcome = evaluate_acceptance(
        baseline_parse_p95_ms=100.0,
        candidate_chunk_p95_ms=100.0,
        baseline_proxy_p95_ms=50.0,
        candidate_proxy_p95_ms=50.0,
        baseline_retrieval_p95_ms=10.0,
        candidate_retrieval_p95_ms=20.01,
        child_hash_sets=[("a",), ("a",)],
    )

    assert outcome["acceptance"]["nfr004Retrieval"] is False
    assert outcome["failureReasons"][-1] == (
        "NFR-004 failed: hybrid retrieval P95 exceeds QA-only retrieval P95 x 2.00"
    )


def test_acceptance_allows_nfr004_within_one_hundred_percent():
    from server.scripts.benchmark_chunking import evaluate_acceptance

    outcome = evaluate_acceptance(
        baseline_parse_p95_ms=100.0,
        candidate_chunk_p95_ms=100.0,
        baseline_proxy_p95_ms=50.0,
        candidate_proxy_p95_ms=50.0,
        baseline_retrieval_p95_ms=10.0,
        candidate_retrieval_p95_ms=19.5,
        child_hash_sets=[("a",), ("a",)],
    )

    assert outcome["acceptance"]["nfr004Retrieval"] is True
    assert not any(
        reason.startswith("NFR-004 failed:") for reason in outcome["failureReasons"]
    )


def test_benchmark_legacy_baseline_uses_raw_document_parse_row_semantics(monkeypatch):
    import server.scripts.benchmark_chunking as benchmark
    import server.app.services.document_parse_service as document_parse_service
    from server.app.services.chunking.contracts import AtomicBlock, BlockType

    calls: list[str] = []

    def legacy_count_spy(content: str) -> int:
        calls.append(content)
        return 41

    monkeypatch.setattr(document_parse_service, "_count_tokens", legacy_count_spy)
    raw = "  Cafe\u0301\r\nbody  "
    baseline = benchmark._legacy_parse_persist(
        (
            AtomicBlock(
                index=7,
                content=raw,
                block_type=BlockType.TEXT,
                source_locator={"sourceIdentity": "unicode.md", "block": 7},
                page_no=3,
                title_path=("Unicode",),
            ),
        )
    )

    assert calls == [raw]
    assert baseline.flat_child_contents == (raw,)
    assert baseline.legacy_rows[0]["tokenCount"] == 41
    assert baseline.legacy_rows[0]["sourceLocator"] == {
        "sourceIdentity": "unicode.md",
        "block": 7,
    }
    assert "LocalTokenCounter" not in benchmark._legacy_parse_persist.__annotations__.get(
        "counter", ""
    )


def test_benchmark_executes_production_orm_persistence_methods(monkeypatch) -> None:
    import server.scripts.benchmark_chunking as benchmark
    from server.app.services.document_parse_service import DocumentParseService

    calls: list[str] = []
    original_legacy = DocumentParseService._write_legacy_chunks
    original_adaptive = DocumentParseService._write_adaptive_chunks

    def trace_legacy(self, *args, **kwargs):
        calls.append("legacy")
        return original_legacy(self, *args, **kwargs)

    def trace_adaptive(self, *args, **kwargs):
        calls.append("adaptive")
        return original_adaptive(self, *args, **kwargs)

    monkeypatch.setattr(DocumentParseService, "_write_legacy_chunks", trace_legacy)
    monkeypatch.setattr(
        DocumentParseService, "_write_adaptive_chunks", trace_adaptive
    )

    benchmark.run_benchmark(BENCHMARK_CORPUS, repeat=1)

    assert "legacy" in calls
    assert "adaptive" in calls


def test_production_benchmark_envelope_rolls_back_each_adaptive_iteration() -> None:
    import server.scripts.benchmark_chunking as benchmark
    from server.app.services.chunking.policy import ChunkPolicy
    from server.app.services.chunking.service import ChunkingService
    from server.app.services.chunking.tokenizer import LocalTokenCounter

    blocks, _summary = benchmark.load_corpus_blocks(BENCHMARK_CORPUS)
    counter = LocalTokenCounter()
    policy = ChunkPolicy(tokenizer_name=counter.name, tokenizer_version=counter.version)
    service = ChunkingService(counter)
    harness = benchmark._new_persistence_harness(service, policy, blocks)
    try:
        first = benchmark._write_production_envelope(harness, blocks, adaptive=True)
        second = benchmark._write_production_envelope(harness, blocks, adaptive=True)
    finally:
        harness.close()

    first_child_hashes = tuple(
        row.content_hash for row in first if row.chunk_level == "CHILD"
    )
    second_child_hashes = tuple(
        row.content_hash for row in second if row.chunk_level == "CHILD"
    )
    assert len(first_child_hashes) > 0
    assert second_child_hashes == first_child_hashes


def test_post_top_k_fusion_proxy_uses_production_channel_budgets():
    from server.app.core.retrieval_config import get_retrieval_config
    from server.app.services.chunking.policy import ChunkPolicy
    from server.app.services.chunking.service import ChunkingService
    from server.app.services.chunking.tokenizer import LocalTokenCounter
    from server.scripts.benchmark_chunking import (
        _build_post_top_k_fusion_proxy_inputs,
        load_corpus_blocks,
    )

    blocks, _summary = load_corpus_blocks(BENCHMARK_CORPUS)
    counter = LocalTokenCounter()
    policy = ChunkPolicy(tokenizer_name=counter.name, tokenizer_version=counter.version)
    result = ChunkingService(counter).chunk(
        blocks, policy, document_title="adaptive chunking benchmark"
    )
    config = get_retrieval_config()
    qa_only, hybrid = _build_post_top_k_fusion_proxy_inputs(
        result, blocks, ("operations approval",), config
    )

    assert len(qa_only[0]) == 2
    assert len(hybrid[0]) == 4
    assert len(qa_only[0][0]) <= config.vector_top_k
    assert len(qa_only[0][1]) <= config.text_top_k
    assert len(hybrid[0][0]) <= config.hybrid_qa_vector_top_k
    assert len(hybrid[0][1]) <= config.hybrid_chunk_vector_top_k
    assert len(hybrid[0][2]) <= config.hybrid_qa_text_top_k
    assert len(hybrid[0][3]) <= config.hybrid_chunk_text_top_k
    assert len(hybrid[0][0]) + len(hybrid[0][1]) <= config.vector_top_k
    assert len(hybrid[0][2]) + len(hybrid[0][3]) <= config.text_top_k


def test_acceptance_reports_independent_gate_failures_without_short_circuiting():
    from server.scripts.benchmark_chunking import evaluate_acceptance

    determinism_only = evaluate_acceptance(
        baseline_parse_p95_ms=100.0,
        candidate_chunk_p95_ms=100.0,
        baseline_proxy_p95_ms=50.0,
        candidate_proxy_p95_ms=50.0,
        baseline_retrieval_p95_ms=10.0,
        candidate_retrieval_p95_ms=10.0,
        child_hash_sets=[("a",), ("b",)],
    )
    assert determinism_only["acceptance"] == {
        "determinismChildHashes": False,
        "nfr003ChunkingCpu": True,
        "postTopKFusionCpuProxy": True,
        "nfr004Retrieval": True,
    }
    assert determinism_only["failureReasons"] == [
        "determinism failed: Child hash sets differ between runs"
    ]

    simultaneous = evaluate_acceptance(
        baseline_parse_p95_ms=100.0,
        candidate_chunk_p95_ms=120.01,
        baseline_proxy_p95_ms=50.0,
        candidate_proxy_p95_ms=65.01,
        baseline_retrieval_p95_ms=10.0,
        candidate_retrieval_p95_ms=20.01,
        child_hash_sets=[("a",), ("a",)],
    )
    assert simultaneous["acceptance"] == {
        "determinismChildHashes": True,
        "nfr003ChunkingCpu": False,
        "postTopKFusionCpuProxy": False,
        "nfr004Retrieval": False,
    }
    assert simultaneous["failureReasons"] == [
        "NFR-003 failed: adaptive parse/persist CPU P95 exceeds legacy parse/persist P95 × 1.20",
        "post-Top-K fusion CPU proxy failed: hybrid P95 exceeds QA-only P95 × 1.30",
        "NFR-004 failed: hybrid retrieval P95 exceeds QA-only retrieval P95 x 2.00",
    ]


def test_benchmark_cli_runs_without_pythonpath_and_writes_proxy_report(tmp_path):
    output = tmp_path / "chunking-benchmark.json"
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)

    result = subprocess.run(
        [
            sys.executable,
            "server/scripts/benchmark_chunking.py",
            "--corpus",
            "server/tests/fixtures/chunking_eval/benchmark_corpus",
            "--repeat",
            "2",
            "--output",
            str(output),
        ],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    report = json.loads(output.read_text(encoding="utf-8"))
    assert result.returncode == (
        0 if report["acceptance"]["nfr004Retrieval"] else 2
    ), result.stderr
    assert report["determinism"]["childHashSetStable"] is True
    assert report["acceptance"]["nfr003ChunkingCpu"] is True
    assert report["acceptance"]["postTopKFusionCpuProxy"] is True
    assert isinstance(report["acceptance"]["nfr004Retrieval"], bool)


def test_benchmark_cli_persists_full_schema_valid_report_before_gate_exit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import server.scripts.benchmark_chunking as benchmark

    output = tmp_path / "failed-benchmark.json"
    failed_report = benchmark.run_benchmark(BENCHMARK_CORPUS, repeat=1)
    failed_report["acceptance"] = {
        "determinismChildHashes": False,
        "nfr003ChunkingCpu": False,
        "postTopKFusionCpuProxy": True,
        "nfr004Retrieval": False,
    }
    failed_report["acceptanceFailureReasons"] = [
        "determinism failed: Child hash sets differ between runs",
        "NFR-003 failed: adaptive parse/persist CPU P95 exceeds legacy parse/persist P95 × 1.20",
        "NFR-004 failed: hybrid retrieval P95 exceeds QA-only retrieval P95 x 2.00",
    ]
    monkeypatch.setattr(benchmark, "run_benchmark", lambda *_args, **_kwargs: failed_report)

    exit_code = benchmark.main(
        [
            "--corpus",
            str(BENCHMARK_CORPUS),
            "--repeat",
            "1",
            "--output",
            str(output),
        ]
    )

    assert exit_code == 2
    persisted = json.loads(output.read_text(encoding="utf-8"))
    assert persisted == failed_report
    benchmark.validate_benchmark_report(persisted)


def test_benchmark_report_validation_rejects_obsolete_timing_and_invalid_gate_reasons():
    from server.scripts.benchmark_chunking import (
        BenchmarkInputError,
        run_benchmark,
        validate_benchmark_report,
    )

    report = run_benchmark(BENCHMARK_CORPUS, repeat=1)
    obsolete_timing = deepcopy(report)
    obsolete_timing["timings"]["parsePersistBaseline"] = {
        "p50Ms": 1.0,
        "p95Ms": 1.0,
    }
    with pytest.raises(BenchmarkInputError, match="timings schema"):
        validate_benchmark_report(obsolete_timing)

    missing_proxy_reason = deepcopy(report)
    missing_proxy_reason["acceptance"] = {
        "determinismChildHashes": True,
        "nfr003ChunkingCpu": True,
        "postTopKFusionCpuProxy": False,
        "nfr004Retrieval": True,
    }
    missing_proxy_reason["acceptanceFailureReasons"] = []
    with pytest.raises(BenchmarkInputError, match="post-Top-K fusion CPU proxy"):
        validate_benchmark_report(missing_proxy_reason)

    unexpected_reason = deepcopy(report)
    unexpected_reason["acceptance"] = {
        "determinismChildHashes": True,
        "nfr003ChunkingCpu": True,
        "postTopKFusionCpuProxy": True,
        "nfr004Retrieval": True,
    }
    unexpected_reason["acceptanceFailureReasons"] = ["unrelated failure"]
    with pytest.raises(BenchmarkInputError, match="unknown gate"):
        validate_benchmark_report(unexpected_reason)

    missing_nfr004_reason = deepcopy(report)
    missing_nfr004_reason["acceptance"]["nfr004Retrieval"] = False
    missing_nfr004_reason["acceptanceFailureReasons"] = []
    with pytest.raises(BenchmarkInputError, match="NFR-004"):
        validate_benchmark_report(missing_nfr004_reason)


def test_tokenizer_unavailability_is_explicit_and_does_not_fallback_to_character_count():
    from server.app.services.chunking.contracts import AtomicBlock, BlockType
    from server.app.services.chunking.policy import ChunkPolicy
    from server.app.services.chunking.service import ChunkingService
    from server.app.services.chunking.tokenizer import TokenizerUnavailableError

    class BrokenCounter:
        name = "broken"
        version = "1.0"

        def count(self, _text: str) -> int:
            raise RuntimeError("tokenizer service unavailable")

        def split_by_token_limit(self, _text: str, _limit: int) -> list[str]:
            raise RuntimeError("tokenizer service unavailable")

    counter = BrokenCounter()
    service = ChunkingService(counter)
    policy = ChunkPolicy(tokenizer_name=counter.name, tokenizer_version=counter.version)
    blocks = [
        AtomicBlock(
            index=0,
            content="tokenizer failure must be visible",
            block_type=BlockType.TEXT,
            source_locator={"line": 1},
        )
    ]

    with pytest.raises(TokenizerUnavailableError, match="CHUNK_TOKENIZER_UNAVAILABLE"):
        service.chunk(blocks, policy, document_title="failure.md")


def test_child_embedding_timeout_after_qa_success_rolls_back_all_vectors():
    from sqlalchemy import select

    from server.app.integrations.model_providers.base import ProviderError
    from server.app.models.document import Document, DocumentStatus
    from server.app.models.logs import TaskRun
    from server.app.models.qa_pair import DocumentChunk, QaPair
    from server.app.services.embedding_service import EmbeddingService
    from server.tests.test_embedding_task import (
        _prepare_adaptive_embedding_job,
        add_default_embedding_model,
    )
    from server.tests.test_qa_split_task import build_qa_session

    class QaThenChildTimeoutAdapter:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def embed_texts(self, texts: list[str]) -> list[list[float]]:
            self.calls.append(list(texts))
            if len(self.calls) == 1:
                return [[0.1, 0.2, 0.3, 0.4] for _ in texts]
            raise ProviderError(
                "EMBEDDING_TIMEOUT", "embedding request timed out", retryable=False
            )

    session, identity = build_qa_session()
    tenant_id, job_id, document_id, _parent, children, _pairs = _prepare_adaptive_embedding_job(
        session, identity
    )
    add_default_embedding_model(session, tenant_id, expected_dimension=4)
    adapter = QaThenChildTimeoutAdapter()

    result = EmbeddingService(
        session,
        provider_factory=lambda *_args, **_kwargs: adapter,
        chunk_indexing_enabled=True,
    ).embed_import_job(job_id)

    document = session.get(Document, document_id)
    qa_pairs = list(session.scalars(select(QaPair).where(QaPair.document_id == document_id)))
    persisted_children = list(
        session.scalars(select(DocumentChunk).where(DocumentChunk.id.in_([item.id for item in children])))
    )
    task_run = session.scalar(select(TaskRun).where(TaskRun.resource_id == job_id))
    assert result.status == "FAILED"
    assert result.error_code == "EMBEDDING_TIMEOUT"
    assert document.status == DocumentStatus.FAILED
    assert task_run.status == "FAILED"
    assert task_run.error["code"] == "EMBEDDING_TIMEOUT"
    assert len(adapter.calls) == 2
    assert adapter.calls[0] == [item.question for item in qa_pairs]
    assert all(call.startswith("文档：Refund SOP") for call in adapter.calls[1])
    assert all(pair.question_embedding is None for pair in qa_pairs)
    assert all(chunk.embedding is None for chunk in persisted_children)


def test_chunk_query_timeout_degrades_only_chunk_channels_and_keeps_qa_evidence(monkeypatch):
    from server.app.services.retrieval_service import ChunkChannelUnavailableError
    from server.tests.test_retrieval_service import (
        _employee_context,
        _hybrid_service,
        _seed_hybrid_evidence,
        _stub_hybrid_channels,
        build_session,
    )

    session, identity = build_session()
    qa_pairs, _chunks = _seed_hybrid_evidence(session, identity)
    service = _hybrid_service(session)
    _stub_hybrid_channels(
        monkeypatch,
        service,
        qa_vector=[(qa_pairs[0], 0.9)],
        qa_text=[(qa_pairs[0], 0.8)],
        chunk_vector=[],
        chunk_text=[],
    )
    monkeypatch.setattr(
        service.repo,
        "search_chunk_vector",
        lambda *_args: (_ for _ in ()).throw(
            ChunkChannelUnavailableError("chunk vector query timed out")
        ),
    )

    result = service.retrieve(_employee_context(identity), "退款需要谁审批？")

    assert result.snapshot["chunkRetrievalDegraded"] is True
    assert result.candidates[0].qa_pair_id == qa_pairs[0].id


def test_parent_query_failure_falls_back_to_winning_child_context(monkeypatch):
    from server.app.core.retrieval_config import get_retrieval_config
    from server.app.services.retrieval_service import RetrievalService
    from server.tests.test_context_hydration import _candidate, _context, _seed_hierarchy
    from server.tests.test_document_permissions import build_session

    class BrokenHydrator:
        def hydrate(self, *_args, **_kwargs):
            raise TimeoutError("parent query timed out")

    session, identity = build_session()
    _parent, children = _seed_hierarchy(session, identity)
    child_candidate = _candidate(children[1], 0.9)
    service = RetrievalService(
        session,
        config=replace(get_retrieval_config(), final_top_k=1),
        hybrid_chunk_retrieval_enabled=True,
        parent_context_enabled=True,
        context_hydration_service=BrokenHydrator(),
    )
    monkeypatch.setattr(service, "_embed_query", lambda *_args: [1.0])
    monkeypatch.setattr(service.tokenizer, "tokenize", lambda _question: ["退款"])
    monkeypatch.setattr(
        service,
        "_retrieve_hybrid",
        lambda *_args: (
            [child_candidate],
            {"qa_vector": [], "qa_text": [], "chunk_vector": [], "chunk_text": []},
            False,
        ),
    )

    result = service.retrieve(_context(identity), "退款怎么审批")

    assert result.candidates[0].chunk_id == children[1].id
    assert result.candidates[0].quote == "精准 Child 引用"
    assert result.candidates[0]._lingxi_context_segments == ()


def test_reranker_failure_preserves_three_item_rrf_order_and_final_top_k(monkeypatch):
    from server.app.core.retrieval_config import get_retrieval_config
    from server.app.models.qa_pair import DocumentChunk
    from server.tests.test_retrieval_service import (
        _employee_context,
        _hybrid_service,
        _seed_hybrid_evidence,
        _stub_hybrid_channels,
        build_session,
    )

    class BrokenReranker:
        def rerank(self, *_args, **_kwargs):
            raise TimeoutError("reranker timed out")

    session, identity = build_session()
    qa_pairs, chunks = _seed_hybrid_evidence(session, identity)
    third_chunk = DocumentChunk(
        tenant_id=identity["tenant"].id,
        document_id=chunks[0].document_id,
        chunk_index=2,
        title_path=["退款", "补充"],
        content="退款例外需要合规审批并记录原因。",
        page_start=3,
        page_end=3,
        source_locator={"block": 3},
        source_locators=[{"block": 3}],
        content_hash="c" * 64,
        embedding=[0.4, 0.6, 0.0, 0.0],
        search_text="退款 例外 合规 审批",
        status="ACTIVE",
        block_type="TEXT",
        chunk_level="CHILD",
    )
    session.add(third_chunk)
    session.commit()

    service = _hybrid_service(session)
    service.config = replace(get_retrieval_config(), rrf_k=10, final_top_k=2)
    service.reranker = BrokenReranker()
    _stub_hybrid_channels(
        monkeypatch,
        service,
        qa_vector=[(qa_pairs[0], 0.91), (qa_pairs[1], 0.70)],
        qa_text=[(qa_pairs[1], 0.81), (qa_pairs[0], 0.60)],
        chunk_vector=[(chunks[0], 0.71), (third_chunk, 0.65), (chunks[1], 0.50)],
        chunk_text=[(third_chunk, 0.61), (chunks[0], 0.55), (chunks[1], 0.40)],
    )

    result = service.retrieve(_employee_context(identity), "退款需要谁审批？")

    assert [candidate.chunk_id for candidate in result.candidates] == [
        chunks[0].id,
        chunks[1].id,
    ]
    assert len(result.snapshot["stages"]["rrf"]) == 3
    assert [item["chunkId"] for item in result.snapshot["stages"]["rerank"]] == [
        chunks[0].id,
        chunks[1].id,
    ]
    assert [candidate.rerank_score for candidate in result.candidates] == [
        candidate.fused_score for candidate in result.candidates
    ]
    assert result.snapshot["rerankerDegraded"] is True
