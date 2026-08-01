import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures" / "chunking_eval"
)


def _span(block: str) -> dict:
    return {"block": block, "_lingxi_chunk_span": {"source_rel_start": 0, "source_rel_end": 20}}


def _queries() -> list[dict]:
    return [
        {"id": "q-entity", "query": "产品代号是什么？", "scenario": "exact_entity"},
        {"id": "q-section", "query": "退款章节的时限？", "scenario": "section_limited"},
        {"id": "q-table", "query": "华北 Q2 收入？", "scenario": "table"},
        {
            "id": "q-private",
            "query": "受限薪酬政策是什么？",
            "scenario": "permission_denied",
        },
    ]


def _expected() -> list[dict]:
    return [
        {
            "queryId": "q-entity",
            "documentId": "exact-entity.md",
            "sourceSpan": _span("entity"),
            "expectedEvidenceId": "entity-1",
            "expectedVisible": True,
            "qaExpected": True,
        },
        {
            "queryId": "q-section",
            "documentId": "section-policy.md",
            "sourceSpan": _span("section"),
            "expectedEvidenceId": "section-1",
            "expectedVisible": True,
            "qaExpected": True,
        },
        {
            "queryId": "q-table",
            "documentId": "revenue-table.md",
            "sourceSpan": _span("table"),
            "expectedEvidenceId": "table-1",
            "expectedVisible": True,
            "qaExpected": True,
        },
        {
            "queryId": "q-private",
            "documentId": "restricted-policy.md",
            "sourceSpan": _span("private"),
            "expectedEvidenceId": "private-1",
            "expectedVisible": False,
            "qaExpected": False,
        },
    ]


def _candidate_rankings() -> list[dict]:
    return [
        {
            "queryId": "q-entity",
            "latencyMs": 10,
            "candidates": [
                {
                    "evidenceId": "entity-1",
                    "documentId": "exact-entity.md",
                    "sourceSpan": _span("entity"),
                },
                {
                    "evidenceId": "entity-1",
                    "documentId": "exact-entity.md",
                    "sourceSpan": _span("entity"),
                },
            ],
        },
        {
            "queryId": "q-section",
            "latencyMs": 20,
            "candidates": [
                {
                    "evidenceId": "wrong-1",
                    "documentId": "exact-entity.md",
                    "sourceSpan": _span("entity"),
                },
                {
                    "evidenceId": "section-1",
                    "documentId": "section-policy.md",
                    "sourceSpan": _span("section"),
                },
            ],
        },
        {
            "queryId": "q-table",
            "latencyMs": 40,
            "candidates": [
                {
                    "evidenceId": "table-1",
                    "documentId": "revenue-table.md",
                    "sourceSpan": _span("table"),
                }
            ],
        },
        {
            "queryId": "q-private",
            "latencyMs": 50,
            "candidates": [
                {
                    "evidenceId": "private-1",
                    "documentId": "restricted-policy.md",
                    "sourceSpan": _span("private"),
                }
            ],
        },
    ]


def test_validate_eval_inputs_rejects_duplicate_query_ids_and_missing_expected_span():
    from server.scripts.evaluate_chunking_retrieval import (
        EvaluationInputError,
        validate_eval_inputs,
    )

    duplicate_queries = _queries() + [_queries()[0]]
    with pytest.raises(EvaluationInputError, match="duplicate query id"):
        validate_eval_inputs(duplicate_queries, _expected())

    malformed_expected = _expected()[:-1]
    malformed_expected[0] = {
        "queryId": "q-entity",
        "documentId": "exact-entity.md",
        "expectedVisible": True,
    }
    with pytest.raises(EvaluationInputError, match="sourceSpan"):
        validate_eval_inputs(_queries(), malformed_expected)


def test_validate_eval_inputs_requires_boolean_qa_expectation():
    from server.scripts.evaluate_chunking_retrieval import (
        EvaluationInputError,
        validate_eval_inputs,
    )

    malformed_expected = _expected()
    malformed_expected[0]["qaExpected"] = "yes"

    with pytest.raises(EvaluationInputError, match="boolean qaExpected"):
        validate_eval_inputs(_queries(), malformed_expected)


def test_validate_eval_inputs_requires_expected_evidence_identifier():
    from server.scripts.evaluate_chunking_retrieval import (
        EvaluationInputError,
        validate_eval_inputs,
    )

    malformed_expected = _expected()
    malformed_expected[0]["expectedEvidenceId"] = ""

    with pytest.raises(EvaluationInputError, match="expectedEvidenceId"):
        validate_eval_inputs(_queries(), malformed_expected)


def test_build_evaluation_report_calculates_deterministic_ranking_and_health_metrics():
    from server.scripts.evaluate_chunking_retrieval import build_evaluation_report

    baseline_rankings = [
        {
            "queryId": "q-entity",
            "latencyMs": 12,
            "candidates": [
                {
                    "evidenceId": "wrong-1",
                    "documentId": "section-policy.md",
                    "sourceSpan": _span("section"),
                },
                {
                    "evidenceId": "entity-1",
                    "documentId": "exact-entity.md",
                    "sourceSpan": _span("entity"),
                },
            ],
        },
        {"queryId": "q-section", "latencyMs": 15, "candidates": []},
        {
            "queryId": "q-table",
            "latencyMs": 24,
            "candidates": [
                {
                    "evidenceId": "table-1",
                    "documentId": "revenue-table.md",
                    "sourceSpan": _span("table"),
                }
            ],
        },
        {"queryId": "q-private", "latencyMs": 30, "candidates": []},
    ]
    chunks = [
        {"tokenCount": 50, "blockType": "TEXT", "chunkLevel": "CHILD", "qaCovered": True},
        {"tokenCount": 810, "blockType": "TEXT", "chunkLevel": "CHILD", "qaCovered": False},
        {"tokenCount": 400, "blockType": "TABLE", "chunkLevel": "CHILD", "qaCovered": True},
    ]

    report = build_evaluation_report(
        queries=_queries(),
        expected=_expected(),
        baseline_rankings=baseline_rankings,
        candidate_rankings=_candidate_rankings(),
        baseline_config_hash="a" * 64,
        candidate_config_hash="b" * 64,
        baseline_mode="qa-only",
        candidate_mode="hybrid",
        chunks=chunks,
        min_tokens=100,
        max_tokens=800,
        index_size={"activeChunkCount": 3, "activeQaPairCount": 2},
        import_latency_ms=[100, 200],
    )

    assert report["baseline"]["metrics"]["recallAt5"] == pytest.approx(2 / 3)
    assert report["baseline"]["metrics"]["mrrAt10"] == pytest.approx(0.5)
    assert report["candidate"]["metrics"]["recallAt10"] == pytest.approx(1.0)
    assert report["candidate"]["metrics"]["mrrAt10"] == pytest.approx(5 / 6)
    assert report["candidate"]["metrics"]["ndcgAt10"] == pytest.approx(
        (1 + 1 / 1.584962500721156 + 1) / 3
    )
    assert report["candidate"]["metrics"]["emptyResultRate"] == pytest.approx(0.0)
    assert report["candidate"]["quality"]["citationAccuracy"] == pytest.approx(2 / 3)
    assert report["candidate"]["quality"]["duplicateRate"] == pytest.approx(1 / 6)
    assert report["candidate"]["quality"]["permissionLeakRate"] == pytest.approx(1.0)
    assert report["chunkHealth"]["tinyChunkCount"] == 1
    assert report["chunkHealth"]["oversizedProseChunkCount"] == 1
    assert report["qaCoverage"]["coveredChildCount"] == 2
    assert report["qaCoverage"]["ratio"] == pytest.approx(2 / 3)
    assert report["candidate"]["latencyMs"] == {"p50": 30.0, "p95": 48.5}
    assert report["baseline"]["configHash"] == "a" * 64
    assert report["candidate"]["configHash"] == "b" * 64


def test_hidden_document_candidate_is_a_permission_leak_even_when_span_differs():
    from server.scripts.evaluate_chunking_retrieval import build_evaluation_report

    hidden_ranking = [
        {"queryId": query["id"], "candidates": []}
        for query in _queries()
    ]
    hidden_ranking[-1]["candidates"] = [
        {
            "evidenceId": "other-restricted-chunk",
            "documentId": "restricted-policy.md",
            "sourceSpan": _span("different-private-block"),
            "content": "不相关的受限文档内容",
        }
    ]

    report = build_evaluation_report(
        queries=_queries(),
        expected=_expected(),
        baseline_rankings=hidden_ranking,
        candidate_rankings=hidden_ranking,
        baseline_config_hash="a" * 64,
        candidate_config_hash="b" * 64,
        baseline_mode="qa-only",
        candidate_mode="hybrid",
        chunks=[],
        min_tokens=100,
        max_tokens=800,
    )

    assert report["candidate"]["quality"]["permissionLeakRate"] == 1.0


def test_import_stage_latency_uses_only_successful_task_runs_with_valid_timestamps():
    from server.scripts.evaluate_chunking_retrieval import import_stage_latency_ms

    started = datetime(2026, 8, 1, tzinfo=timezone.utc)
    task_runs = [
        SimpleNamespace(
            status="SUCCESS",
            created_at=started,
            updated_at=started + timedelta(milliseconds=125),
        ),
        SimpleNamespace(
            status="COMPLETED",
            created_at=started,
            updated_at=started + timedelta(milliseconds=200),
        ),
        SimpleNamespace(status="SUCCESS", created_at=started, updated_at=None),
    ]

    assert import_stage_latency_ms(task_runs) == [125.0]


def test_build_evaluation_report_rejects_non_sha256_config_hashes():
    from server.scripts.evaluate_chunking_retrieval import (
        EvaluationInputError,
        build_evaluation_report,
    )

    with pytest.raises(EvaluationInputError, match="baseline config hash"):
        build_evaluation_report(
            queries=_queries(),
            expected=_expected(),
            baseline_rankings=[],
            candidate_rankings=[],
            baseline_config_hash="not-a-sha256",
            candidate_config_hash="b" * 64,
            baseline_mode="qa-only",
            candidate_mode="hybrid",
            chunks=[],
            min_tokens=100,
            max_tokens=800,
        )


def test_validate_fixture_document_records_rejects_non_ready_or_duplicate_filenames():
    from server.scripts.evaluate_chunking_retrieval import (
        EvaluationRuntimeError,
        validate_fixture_document_records,
    )

    with pytest.raises(EvaluationRuntimeError, match="EVALUATION_CORPUS_NOT_READY"):
        validate_fixture_document_records(
            {"exact-entity.md"},
            [("doc-1", "exact-entity.md", "EMBEDDING")],
        )

    with pytest.raises(EvaluationRuntimeError, match="EVALUATION_CORPUS_AMBIGUOUS"):
        validate_fixture_document_records(
            {"exact-entity.md"},
            [
                ("doc-1", "exact-entity.md", "READY"),
                ("doc-2", "exact-entity.md", "READY"),
            ],
        )


def test_write_reports_emits_json_and_markdown(tmp_path):
    from server.scripts.evaluate_chunking_retrieval import (
        build_evaluation_report,
        write_reports,
    )

    report = build_evaluation_report(
        queries=_queries(),
        expected=_expected(),
        baseline_rankings=[],
        candidate_rankings=[],
        baseline_config_hash="a" * 64,
        candidate_config_hash="b" * 64,
        baseline_mode="qa-only",
        candidate_mode="hybrid",
        chunks=[],
        min_tokens=100,
        max_tokens=800,
    )

    json_path, markdown_path = write_reports(tmp_path, report)

    assert json.loads(json_path.read_text(encoding="utf-8"))["dataset"]["queryCount"] == 4
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "Chunking retrieval quality evaluation" in markdown
    assert "qa-only" in markdown
    assert "hybrid" in markdown
    assert "Token distribution by block type" in markdown


def test_fixture_dataset_is_versioned_and_covers_required_scenarios():
    from server.scripts.evaluate_chunking_retrieval import load_jsonl, validate_eval_inputs

    queries = load_jsonl(FIXTURE_ROOT / "queries.jsonl")
    expected = load_jsonl(FIXTURE_ROOT / "expected_evidence.jsonl")
    validate_eval_inputs(queries, expected)

    assert {query["scenario"] for query in queries} == {
        "exact_entity",
        "section_limited",
        "cross_paragraph",
        "table",
        "code_symbol",
        "formula_explanation",
        "image_caption",
        "qa_gap",
        "permission_denied",
    }
    assert {path.name for path in (FIXTURE_ROOT / "corpus").iterdir()} >= {
        "exact-entity.md",
        "section-policy.md",
        "cross-paragraph.md",
        "revenue-table.md",
        "billing.py",
        "formula.md",
        "image-caption.md",
        "qa-gap.md",
        "restricted-policy.md",
    }


def test_evaluator_script_runs_directly_without_pythonpath_and_fails_closed(tmp_path):
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    output_path = tmp_path / "chunking-eval-cli-test"
    result = subprocess.run(
        [
            sys.executable,
            "server/scripts/evaluate_chunking_retrieval.py",
            "--queries",
            "server/tests/fixtures/chunking_eval/queries.jsonl",
            "--expected",
            "server/tests/fixtures/chunking_eval/expected_evidence.jsonl",
            "--baseline-mode",
            "qa-only",
            "--candidate-mode",
            "hybrid",
            "--output",
            str(output_path),
            "--tenant-id",
            "missing-tenant",
            "--user-id",
            "missing-user",
        ],
        cwd=Path(__file__).parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "EMBEDDING_MODEL_MISSING" in result.stderr
    assert not output_path.exists()


def test_require_embedding_model_fails_with_explicit_code():
    from server.scripts.evaluate_chunking_retrieval import (
        EvaluationRuntimeError,
        require_embedding_model,
    )

    class MissingEmbeddingService:
        def __init__(self, _session):
            pass

        def _default_model(self, _tenant_id):
            raise RuntimeError("not configured")

    with pytest.raises(EvaluationRuntimeError, match="EMBEDDING_MODEL_MISSING"):
        require_embedding_model(object(), "tenant-1", MissingEmbeddingService)
