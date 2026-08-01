"""Evaluate a frozen chunking/retrieval corpus against QA-only and hybrid modes.

The pure functions in this module intentionally do not depend on a database or
model provider.  They make the versioned fixture contract and metric
calculation repeatable in CI.  The CLI is deliberately stricter: it requires a
real tenant/user, corpus documents already indexed in that tenant, and an
active default embedding model.  It never uses RetrievalService's test-only
fallback embedding path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping

from sqlalchemy import func, select


_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

_VALID_MODES = frozenset({"qa-only", "hybrid"})
_HEX_HASH_LENGTH = 64


class EvaluationInputError(ValueError):
    """The frozen evaluation corpus is malformed or internally inconsistent."""


class EvaluationRuntimeError(RuntimeError):
    """The configured live evaluation environment cannot produce trustworthy data."""


def load_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Load a UTF-8 JSONL file while preserving its versioned row order."""

    location = Path(path)
    if not location.is_file():
        raise EvaluationInputError(f"evaluation input does not exist: {location}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(location.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationInputError(
                f"invalid JSONL at {location}:{line_number}: {exc.msg}"
            ) from exc
        if not isinstance(row, dict):
            raise EvaluationInputError(
                f"JSONL row at {location}:{line_number} must be an object"
            )
        rows.append(row)
    if not rows:
        raise EvaluationInputError(f"evaluation input is empty: {location}")
    return rows


def validate_eval_inputs(
    queries: Iterable[Mapping[str, Any]],
    expected: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Validate the frozen corpus and return expected evidence by query id.

    One expected source is required for every query.  A denied-access case is
    still given an expected document/span so the evaluator can detect a leak;
    it is excluded from recall and ranking-quality denominators.
    """

    query_rows = [dict(row) for row in queries]
    expected_rows = [dict(row) for row in expected]
    query_ids: set[str] = set()
    for row in query_rows:
        query_id = row.get("id")
        if not isinstance(query_id, str) or not query_id.strip():
            raise EvaluationInputError("query id must be a non-empty string")
        if query_id in query_ids:
            raise EvaluationInputError(f"duplicate query id: {query_id}")
        query_ids.add(query_id)
        if not isinstance(row.get("query"), str) or not row["query"].strip():
            raise EvaluationInputError(f"query {query_id} must contain non-empty query")
        if not isinstance(row.get("scenario"), str) or not row["scenario"].strip():
            raise EvaluationInputError(f"query {query_id} must contain scenario")

    expected_by_query: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in expected_rows:
        query_id = row.get("queryId")
        document_id = row.get("documentId")
        source_span = row.get("sourceSpan")
        if not isinstance(query_id, str) or not query_id.strip():
            raise EvaluationInputError("expected evidence queryId must be a non-empty string")
        if not isinstance(document_id, str) or not document_id.strip():
            raise EvaluationInputError(
                f"expected evidence for {query_id} must contain documentId"
            )
        if not isinstance(source_span, dict) or not source_span:
            raise EvaluationInputError(
                f"expected evidence for {query_id} must contain sourceSpan"
            )
        if not isinstance(row.get("expectedEvidenceId"), str) or not row[
            "expectedEvidenceId"
        ].strip():
            raise EvaluationInputError(
                f"expected evidence for {query_id} must contain expectedEvidenceId"
            )
        if not isinstance(row.get("expectedVisible"), bool):
            raise EvaluationInputError(
                f"expected evidence for {query_id} must contain boolean expectedVisible"
            )
        if not isinstance(row.get("qaExpected"), bool):
            raise EvaluationInputError(
                f"expected evidence for {query_id} must contain boolean qaExpected"
            )
        if query_id not in query_ids:
            raise EvaluationInputError(
                f"expected evidence references unknown query id: {query_id}"
            )
        expected_by_query[query_id].append(row)

    missing = sorted(query_ids - set(expected_by_query))
    if missing:
        raise EvaluationInputError(
            "every query must have expected document/source span; missing: "
            + ", ".join(missing)
        )
    return dict(expected_by_query)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _dataset_hash(queries: list[dict[str, Any]], expected: list[dict[str, Any]]) -> str:
    payload = {"queries": queries, "expectedEvidence": expected}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _percentile(values: Iterable[float | int], percentile: float) -> float | None:
    sorted_values = sorted(float(value) for value in values)
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    lower_value = sorted_values[lower]
    upper_value = sorted_values[upper]
    return lower_value + (upper_value - lower_value) * (position - lower)


def _require_config_hash(config_hash: str, label: str) -> None:
    if not isinstance(config_hash, str) or len(config_hash) != _HEX_HASH_LENGTH:
        raise EvaluationInputError(f"{label} config hash must be a 64-character SHA-256")
    try:
        int(config_hash, 16)
    except ValueError as exc:
        raise EvaluationInputError(
            f"{label} config hash must be a hexadecimal SHA-256"
        ) from exc


def _candidate_matches_expected(
    candidate: Mapping[str, Any], expected: Mapping[str, Any]
) -> bool:
    if candidate.get("documentId") != expected["documentId"]:
        return False
    source_span = expected["sourceSpan"]
    # Anchor text makes a corpus portable across parser locator implementations,
    # while retaining a precise, versioned evidence span in the fixture.
    anchor = source_span.get("anchorText")
    if isinstance(anchor, str) and anchor:
        content = candidate.get("content")
        return isinstance(content, str) and anchor in content
    return _canonical_json(candidate.get("sourceSpan") or {}) == _canonical_json(
        source_span
    )


def _candidate_identity(candidate: Mapping[str, Any]) -> str:
    evidence_id = candidate.get("evidenceId")
    if isinstance(evidence_id, str) and evidence_id:
        return f"evidence:{evidence_id}"
    return "span:" + _canonical_json(
        {
            "documentId": candidate.get("documentId"),
            "sourceSpan": candidate.get("sourceSpan") or {},
            "content": candidate.get("content") or "",
        }
    )


def _evaluate_rankings(
    queries: list[dict[str, Any]],
    expected_by_query: Mapping[str, list[dict[str, Any]]],
    rankings: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    rankings_by_query: dict[str, dict[str, Any]] = {}
    known_query_ids = {row["id"] for row in queries}
    for row in rankings:
        query_id = row.get("queryId")
        if query_id not in known_query_ids:
            raise EvaluationInputError(f"ranking references unknown query id: {query_id}")
        if query_id in rankings_by_query:
            raise EvaluationInputError(f"duplicate ranking result for query id: {query_id}")
        candidates = row.get("candidates", [])
        if not isinstance(candidates, list):
            raise EvaluationInputError(f"ranking candidates must be a list: {query_id}")
        rankings_by_query[query_id] = dict(row)

    recalls_at_5: list[float] = []
    recalls_at_10: list[float] = []
    reciprocal_ranks: list[float] = []
    normalized_dcg: list[float] = []
    empty_results: list[float] = []
    citation_matches: list[float] = []
    all_candidate_count = 0
    all_duplicate_count = 0
    permission_cases = 0
    permission_leaks = 0
    latencies: list[float] = []

    for query in queries:
        query_id = query["id"]
        result = rankings_by_query.get(query_id, {"candidates": []})
        candidates = list(result.get("candidates", []))
        for candidate in candidates:
            if not isinstance(candidate, Mapping):
                raise EvaluationInputError(
                    f"ranking candidate must be an object: {query_id}"
                )
        latency = result.get("latencyMs")
        if isinstance(latency, (int, float)) and not isinstance(latency, bool):
            latencies.append(float(latency))

        identities = [_candidate_identity(candidate) for candidate in candidates[:10]]
        all_candidate_count += len(identities)
        all_duplicate_count += len(identities) - len(set(identities))

        expectations = expected_by_query[query_id]
        expected_visible = all(row["expectedVisible"] for row in expectations)
        if not expected_visible:
            permission_cases += 1
            if any(
                candidate.get("documentId") == expectation["documentId"]
                for candidate in candidates
                for expectation in expectations
            ):
                permission_leaks += 1
            continue

        first_match_rank: int | None = None
        for rank, candidate in enumerate(candidates[:10], 1):
            if any(
                _candidate_matches_expected(candidate, expectation)
                for expectation in expectations
            ):
                first_match_rank = rank
                break

        recalls_at_5.append(float(first_match_rank is not None and first_match_rank <= 5))
        recalls_at_10.append(float(first_match_rank is not None))
        reciprocal_ranks.append(1 / first_match_rank if first_match_rank else 0.0)
        normalized_dcg.append(
            1 / math.log2(first_match_rank + 1) if first_match_rank else 0.0
        )
        empty_results.append(float(not candidates))
        citation_matches.append(float(first_match_rank == 1))

    evaluated_query_count = len(recalls_at_10)
    if not evaluated_query_count:
        raise EvaluationInputError("evaluation set has no expectedVisible query")

    return {
        "metrics": {
            "recallAt5": mean(recalls_at_5),
            "recallAt10": mean(recalls_at_10),
            "mrrAt10": mean(reciprocal_ranks),
            "ndcgAt10": mean(normalized_dcg),
            "emptyResultRate": mean(empty_results),
        },
        "quality": {
            "citationAccuracy": mean(citation_matches),
            "duplicateRate": (
                all_duplicate_count / all_candidate_count if all_candidate_count else 0.0
            ),
            "permissionLeakRate": (
                permission_leaks / permission_cases if permission_cases else 0.0
            ),
            "permissionCaseCount": permission_cases,
        },
        "latencyMs": {
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
        },
        "evaluatedQueryCount": evaluated_query_count,
    }


def _chunk_health(
    chunks: Iterable[Mapping[str, Any]], min_tokens: int, max_tokens: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    chunk_rows = [dict(chunk) for chunk in chunks]
    token_counts = [
        int(chunk["tokenCount"])
        for chunk in chunk_rows
        if isinstance(chunk.get("tokenCount"), int) and not isinstance(chunk["tokenCount"], bool)
    ]
    tiny = [count for count in token_counts if count < min_tokens]
    oversized = [
        chunk
        for chunk in chunk_rows
        if chunk.get("blockType") in {"TEXT", "PROSE"}
        and isinstance(chunk.get("tokenCount"), int)
        and chunk["tokenCount"] > max_tokens
    ]
    children = [
        chunk
        for chunk in chunk_rows
        if str(chunk.get("chunkLevel", "CHILD")).upper() == "CHILD"
    ]
    covered = [chunk for chunk in children if chunk.get("qaCovered") is True]
    token_by_type = Counter(
        str(chunk.get("blockType", "UNKNOWN"))
        for chunk in chunk_rows
        if isinstance(chunk.get("tokenCount"), int)
    )
    return (
        {
            "chunkCount": len(chunk_rows),
            "tinyChunkCount": len(tiny),
            "oversizedProseChunkCount": len(oversized),
            "tokenDistribution": {
                "count": len(token_counts),
                "min": min(token_counts) if token_counts else None,
                "max": max(token_counts) if token_counts else None,
                "mean": mean(token_counts) if token_counts else None,
                "p50": _percentile(token_counts, 0.5),
                "p95": _percentile(token_counts, 0.95),
                "byBlockType": dict(sorted(token_by_type.items())),
            },
        },
        {
            "childChunkCount": len(children),
            "coveredChildCount": len(covered),
            "ratio": len(covered) / len(children) if children else 0.0,
        },
    )


def _latency_summary(values: Iterable[float | int] | None) -> dict[str, Any]:
    values = list(values or [])
    return {
        "observationCount": len(values),
        "p50": _percentile(values, 0.5),
        "p95": _percentile(values, 0.95),
    }


def import_stage_latency_ms(task_runs: Iterable[Any]) -> list[float]:
    """Return successful task-stage durations without inventing import envelopes."""

    durations: list[float] = []
    for task_run in task_runs:
        if getattr(task_run, "status", None) != "SUCCESS":
            continue
        created_at = getattr(task_run, "created_at", None)
        updated_at = getattr(task_run, "updated_at", None)
        if created_at is None or updated_at is None:
            continue
        duration_ms = (updated_at - created_at).total_seconds() * 1000
        if duration_ms >= 0:
            durations.append(duration_ms)
    return durations


def build_evaluation_report(
    *,
    queries: Iterable[Mapping[str, Any]],
    expected: Iterable[Mapping[str, Any]],
    baseline_rankings: Iterable[Mapping[str, Any]],
    candidate_rankings: Iterable[Mapping[str, Any]],
    baseline_config_hash: str,
    candidate_config_hash: str,
    baseline_mode: str,
    candidate_mode: str,
    chunks: Iterable[Mapping[str, Any]],
    min_tokens: int,
    max_tokens: int,
    index_size: Mapping[str, Any] | None = None,
    import_latency_ms: Iterable[float | int] | None = None,
) -> dict[str, Any]:
    """Build the deterministic JSON-serializable comparison report."""

    query_rows = [dict(row) for row in queries]
    expected_rows = [dict(row) for row in expected]
    expected_by_query = validate_eval_inputs(query_rows, expected_rows)
    if baseline_mode not in _VALID_MODES or candidate_mode not in _VALID_MODES:
        raise EvaluationInputError(
            f"modes must be one of {sorted(_VALID_MODES)}"
        )
    if baseline_mode == candidate_mode:
        raise EvaluationInputError("baseline and candidate modes must differ")
    _require_config_hash(baseline_config_hash, "baseline")
    _require_config_hash(candidate_config_hash, "candidate")
    if min_tokens <= 0 or max_tokens < min_tokens:
        raise EvaluationInputError("chunk token bounds must satisfy 0 < min <= max")

    chunk_health, qa_coverage = _chunk_health(chunks, min_tokens, max_tokens)
    return {
        "schemaVersion": 1,
        "dataset": {
            "hash": _dataset_hash(query_rows, expected_rows),
            "queryCount": len(query_rows),
            "expectedEvidenceCount": len(expected_rows),
            "scenarioCounts": dict(
                sorted(Counter(str(row["scenario"]) for row in query_rows).items())
            ),
        },
        "baseline": {
            "mode": baseline_mode,
            "configHash": baseline_config_hash,
            **_evaluate_rankings(query_rows, expected_by_query, baseline_rankings),
        },
        "candidate": {
            "mode": candidate_mode,
            "configHash": candidate_config_hash,
            **_evaluate_rankings(query_rows, expected_by_query, candidate_rankings),
        },
        "chunkHealth": chunk_health,
        "qaCoverage": qa_coverage,
        "indexSize": dict(index_size or {}),
        "importLatencyMs": _latency_summary(import_latency_ms),
    }


def _format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a concise, review-friendly companion to the JSON report."""

    baseline = report["baseline"]
    candidate = report["candidate"]
    health = report["chunkHealth"]
    coverage = report["qaCoverage"]
    lines = [
        "# Chunking retrieval quality evaluation",
        "",
        f"- Dataset hash: `{report['dataset']['hash']}`",
        f"- Queries: {report['dataset']['queryCount']}",
        f"- Baseline: `{baseline['mode']}` (`{baseline['configHash']}`)",
        f"- Candidate: `{candidate['mode']}` (`{candidate['configHash']}`)",
        "",
        "## Retrieval quality",
        "",
        "| Metric | Baseline | Candidate |",
        "|---|---:|---:|",
    ]
    for key in ("recallAt5", "recallAt10", "mrrAt10", "ndcgAt10", "emptyResultRate"):
        lines.append(
            f"| {key} | {_format_number(baseline['metrics'][key])} | "
            f"{_format_number(candidate['metrics'][key])} |"
        )
    lines.extend(
        [
            "",
            "## Evidence and performance",
            "",
            "| Metric | Baseline | Candidate |",
            "|---|---:|---:|",
        ]
    )
    for section, key in (
        ("citationAccuracy", "citationAccuracy"),
        ("duplicateRate", "duplicateRate"),
        ("permissionLeakRate", "permissionLeakRate"),
    ):
        lines.append(
            f"| {section} | {_format_number(baseline['quality'][key])} | "
            f"{_format_number(candidate['quality'][key])} |"
        )
    for key in ("p50", "p95"):
        lines.append(
            f"| queryLatencyMs.{key} | {_format_number(baseline['latencyMs'][key])} | "
            f"{_format_number(candidate['latencyMs'][key])} |"
        )
    lines.extend(
        [
            "",
            "## Chunk health",
            "",
            f"- Chunk count: {health['chunkCount']}",
            f"- Tiny chunks: {health['tinyChunkCount']}",
            f"- Oversized prose chunks: {health['oversizedProseChunkCount']}",
            f"- Token distribution (count/min/max/mean): "
            f"{_format_number(health['tokenDistribution']['count'])} / "
            f"{_format_number(health['tokenDistribution']['min'])} / "
            f"{_format_number(health['tokenDistribution']['max'])} / "
            f"{_format_number(health['tokenDistribution']['mean'])}",
            f"- Token P50/P95: {_format_number(health['tokenDistribution']['p50'])}"
            f" / {_format_number(health['tokenDistribution']['p95'])}",
            "- Token distribution by block type: "
            f"`{_canonical_json(health['tokenDistribution']['byBlockType'])}`",
            f"- QA coverage: {coverage['coveredChildCount']}/{coverage['childChunkCount']}"
            f" ({_format_number(coverage['ratio'])})",
            "",
            "## Index/import observations",
            "",
            f"- Index: `{_canonical_json(report['indexSize'])}`",
            f"- Import latency observations: {report['importLatencyMs']['observationCount']}",
            f"- Import latency P50/P95: "
            f"{_format_number(report['importLatencyMs']['p50'])} / "
            f"{_format_number(report['importLatencyMs']['p95'])}",
            "",
        ]
    )
    return "\n".join(lines)


def write_reports(output: str | Path, report: Mapping[str, Any]) -> tuple[Path, Path]:
    destination = Path(output)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "chunking-evaluation.json"
    markdown_path = destination / "chunking-evaluation.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def require_embedding_model(
    session: Any,
    tenant_id: str,
    embedding_service_factory: Callable[[Any], Any] | None = None,
) -> tuple[Any, Any]:
    """Fail closed if a live evaluation cannot use a configured embedding model."""

    if embedding_service_factory is None:
        from server.app.services.embedding_service import EmbeddingService

        embedding_service_factory = EmbeddingService
    try:
        return embedding_service_factory(session)._default_model(tenant_id)
    except Exception as exc:
        raise EvaluationRuntimeError(
            "EMBEDDING_MODEL_MISSING: active default embedding model is required "
            f"for tenant {tenant_id}; evaluation will not use fallback embeddings"
        ) from exc


def _live_access_context(session: Any, tenant_id: str, user_id: str):
    from server.app.core.permissions import AccessContext
    from server.app.models.permission import Permission
    from server.app.models.role import Role, RolePermission, UserRole
    from server.app.models.user import User

    user = session.get(User, user_id)
    if user is None or user.tenant_id != tenant_id or user.status != "ACTIVE":
        raise EvaluationRuntimeError(
            "EVALUATION_USER_INVALID: user must be ACTIVE and belong to --tenant-id"
        )
    rows = session.execute(
        select(Role.id, Role.code, Permission.code)
        .select_from(UserRole)
        .join(Role, Role.id == UserRole.role_id)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .outerjoin(Permission, Permission.id == RolePermission.permission_id)
        .where(UserRole.user_id == user.id)
    ).all()
    role_ids: list[str] = []
    role_codes: set[str] = set()
    permissions: set[str] = set()
    seen_role_ids: set[str] = set()
    for role_id, role_code, permission_code in rows:
        if role_id not in seen_role_ids:
            role_ids.append(role_id)
            role_codes.add(role_code)
            seen_role_ids.add(role_id)
        if permission_code:
            permissions.add(permission_code)
    return AccessContext(
        tenant_id=user.tenant_id,
        user_id=user.id,
        department_id=user.department_id,
        role_ids=role_ids,
        permissions=permissions,
        email=user.email,
        name=user.name,
        role_codes=role_codes,
    )


def _fixture_document_map(
    session: Any, tenant_id: str, expected: Iterable[Mapping[str, Any]]
) -> tuple[dict[str, str], dict[str, str]]:
    from server.app.models.document import Document

    file_names = sorted({str(row["documentId"]) for row in expected})
    rows = session.execute(
        select(Document.id, Document.file_name, Document.status).where(
            Document.tenant_id == tenant_id, Document.file_name.in_(file_names)
        )
    ).all()
    file_to_document_id = validate_fixture_document_records(file_names, rows)
    return file_to_document_id, {
        document_id: file_name for file_name, document_id in file_to_document_id.items()
    }


def validate_fixture_document_records(
    expected_file_names: Iterable[str],
    document_records: Iterable[tuple[str, str, Any]],
) -> dict[str, str]:
    """Require one READY document per frozen corpus filename."""

    expected_names = set(expected_file_names)
    records = list(document_records)
    file_to_document_id = {file_name: document_id for document_id, file_name, _ in records}
    missing = sorted(expected_names - set(file_to_document_id))
    if missing:
        raise EvaluationRuntimeError(
            "EVALUATION_CORPUS_NOT_INDEXED: missing corpus documents in tenant: "
            + ", ".join(missing)
        )
    if len(file_to_document_id) != len(records):
        raise EvaluationRuntimeError(
            "EVALUATION_CORPUS_AMBIGUOUS: fixture file names must be unique per tenant"
        )
    not_ready = sorted(
        file_name
        for _document_id, file_name, status in records
        if status != "READY"
    )
    if not_ready:
        raise EvaluationRuntimeError(
            "EVALUATION_CORPUS_NOT_READY: corpus documents must be READY: "
            + ", ".join(not_ready)
        )
    return file_to_document_id


def _strict_query_embedder(session: Any, tenant_id: str) -> Callable[[str, str], list[float]]:
    from server.app.core.secrets import decrypt_secret
    from server.app.integrations.model_providers.registry import build_provider_adapter

    model, provider = require_embedding_model(session, tenant_id)
    adapter = build_provider_adapter(
        provider.provider_type,
        provider.base_url,
        decrypt_secret(provider.encrypted_api_key),
        {**(provider.config or {}), **(model.config or {})},
        model_name=model.model_name,
        timeout_ms=model.timeout_ms,
    )

    def embed(request_tenant_id: str, question: str) -> list[float]:
        if request_tenant_id != tenant_id:
            raise EvaluationRuntimeError(
                "EVALUATION_TENANT_MISMATCH: evaluator cannot embed a different tenant"
            )
        try:
            vectors = adapter.embed_texts([question])
        except Exception as exc:
            raise EvaluationRuntimeError(
                "EMBEDDING_QUERY_FAILED: live evaluation will not manufacture "
                "fallback vectors"
            ) from exc
        if not vectors or not isinstance(vectors[0], list):
            raise EvaluationRuntimeError(
                "EMBEDDING_QUERY_FAILED: provider returned no query vector"
            )
        return vectors[0]

    return embed


def _scope_for_query(
    query: Mapping[str, Any], file_to_document_id: Mapping[str, str]
):
    from server.app.schemas.retrieval import RetrievalAccessScope

    raw = query.get("accessScope")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise EvaluationInputError(
            f"query {query['id']} accessScope must be an object"
        )
    files = raw.get("documentFileNames")
    document_ids = None
    if files is not None:
        if not isinstance(files, list) or not all(isinstance(value, str) for value in files):
            raise EvaluationInputError(
                f"query {query['id']} accessScope.documentFileNames must be a string list"
            )
        missing = sorted(set(files) - set(file_to_document_id))
        if missing:
            raise EvaluationInputError(
                f"query {query['id']} references unknown fixture documents: {missing}"
            )
        document_ids = {file_to_document_id[file_name] for file_name in files}
    return RetrievalAccessScope(
        document_ids=document_ids,
        space_id=raw.get("spaceId"),
        classification_department_id=raw.get("classificationDepartmentId"),
        category_id=raw.get("categoryId"),
    )


def _qa_source_metadata(session: Any, document_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    from server.app.models.qa_pair import DocumentChunk, QaPair

    rows = session.execute(
        select(
            QaPair.id,
            DocumentChunk.source_locator,
            DocumentChunk.source_locators,
            DocumentChunk.content,
        )
        .outerjoin(DocumentChunk, DocumentChunk.id == QaPair.chunk_id)
        .where(QaPair.document_id.in_(list(document_ids)))
    ).all()
    return {
        qa_id: {
            "sourceSpan": source_locators or source_locator or {},
            "content": content or "",
        }
        for qa_id, source_locator, source_locators, content in rows
    }


def _run_live_mode(
    *,
    session: Any,
    context: Any,
    mode: str,
    queries: list[dict[str, Any]],
    file_to_document_id: Mapping[str, str],
    document_id_to_file: Mapping[str, str],
) -> tuple[list[dict[str, Any]], str]:
    from server.app.core.config import settings, validate_chunking_config
    from server.app.core.retrieval_config import get_retrieval_config
    from server.app.services.retrieval_service import RetrievalService

    validate_chunking_config(settings)
    hybrid = mode == "hybrid"
    service = RetrievalService(
        session,
        config=get_retrieval_config(settings),
        hybrid_chunk_retrieval_enabled=hybrid,
        parent_context_enabled=hybrid and settings.parent_context_enabled,
        rrf_channel_weights=settings.retrieval_rrf_channel_weights,
    )
    service._embed_query = _strict_query_embedder(session, context.tenant_id)
    qa_metadata = _qa_source_metadata(session, document_id_to_file)
    rankings: list[dict[str, Any]] = []
    config_hashes: set[str] = set()
    for query in queries:
        started = perf_counter()
        result = service.retrieve(
            context,
            query["query"],
            access_scope=_scope_for_query(query, file_to_document_id),
        )
        candidates: list[dict[str, Any]] = []
        for candidate in result.candidates:
            qa_metadata_row = qa_metadata.get(candidate.qa_pair_id or "", {})
            candidates.append(
                {
                    "evidenceId": candidate.evidence_id or candidate.qa_pair_id,
                    "documentId": document_id_to_file.get(
                        candidate.document_id, candidate.document_id
                    ),
                    "sourceSpan": candidate.source_locator
                    or qa_metadata_row.get("sourceSpan", {}),
                    "content": candidate.content
                    or qa_metadata_row.get("content")
                    or candidate.answer,
                }
            )
        config_hash = result.snapshot.get("retrievalConfigHash")
        if not isinstance(config_hash, str):
            raise EvaluationRuntimeError(
                "EVALUATION_CONFIG_HASH_MISSING: retrieval snapshot did not expose config hash"
            )
        config_hashes.add(config_hash)
        rankings.append(
            {
                "queryId": query["id"],
                "latencyMs": (perf_counter() - started) * 1000,
                "candidates": candidates,
            }
        )
    if len(config_hashes) != 1:
        raise EvaluationRuntimeError(
            "EVALUATION_CONFIG_HASH_INCONSISTENT: a mode changed during evaluation"
        )
    return rankings, next(iter(config_hashes))


def _live_chunk_health(
    session: Any, document_ids: Iterable[str]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    from server.app.models.qa_pair import DocumentChunk, QaPair

    document_ids = list(document_ids)
    chunks = list(
        session.scalars(
            select(DocumentChunk).where(
                DocumentChunk.document_id.in_(document_ids),
                DocumentChunk.status == "ACTIVE",
                DocumentChunk.chunk_level == "CHILD",
            )
        )
    )
    covered_chunk_ids = set(
        session.scalars(
            select(QaPair.chunk_id).where(
                QaPair.document_id.in_(document_ids),
                QaPair.status == "ACTIVE",
                QaPair.chunk_id.is_not(None),
            )
        )
    )
    active_qa_pair_count = session.scalar(
        select(func.count(QaPair.id)).where(
            QaPair.document_id.in_(document_ids), QaPair.status == "ACTIVE"
        )
    ) or 0
    return (
        [
            {
                "tokenCount": chunk.token_count,
                "blockType": chunk.block_type,
                "chunkLevel": chunk.chunk_level,
                "qaCovered": chunk.id in covered_chunk_ids,
            }
            for chunk in chunks
        ],
        {
            "activeChunkCount": len(chunks),
            "activeQaPairCount": active_qa_pair_count,
            "embeddedChunkCount": sum(1 for chunk in chunks if chunk.embedding is not None),
            "estimatedContentBytes": sum(
                len(chunk.content.encode("utf-8")) for chunk in chunks
            ),
        },
    )


def _live_import_stage_latency_ms(session: Any, document_ids: Iterable[str]) -> list[float]:
    """Measure completed pipeline stages associated with fixture import jobs.

    The current schema has no end-to-end import envelope timestamp.  These are
    therefore explicitly stage durations (`TaskRun.created_at` to
    `TaskRun.updated_at`) for successful tasks joined to the fixture documents.
    """

    from server.app.models.import_job import ImportJob
    from server.app.models.logs import TaskRun

    task_runs = session.scalars(
        select(TaskRun)
        .join(ImportJob, TaskRun.resource_id == ImportJob.id)
        .where(
            ImportJob.document_id.in_(list(document_ids)),
            ImportJob.status == "COMPLETED",
            TaskRun.status == "SUCCESS",
        )
    )
    return import_stage_latency_ms(task_runs)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Evaluate frozen chunking retrieval fixtures on an indexed tenant"
    )
    parser.add_argument("--queries", required=True)
    parser.add_argument("--expected", required=True)
    parser.add_argument("--baseline-mode", choices=sorted(_VALID_MODES), required=True)
    parser.add_argument("--candidate-mode", choices=sorted(_VALID_MODES), required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--tenant-id", default=os.getenv("CHUNKING_EVAL_TENANT_ID"))
    parser.add_argument("--user-id", default=os.getenv("CHUNKING_EVAL_USER_ID"))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    if not args.tenant_id or not args.user_id:
        raise EvaluationRuntimeError(
            "EVALUATION_IDENTITY_REQUIRED: provide --tenant-id/--user-id or "
            "CHUNKING_EVAL_TENANT_ID/CHUNKING_EVAL_USER_ID"
        )
    queries = load_jsonl(args.queries)
    expected = load_jsonl(args.expected)
    validate_eval_inputs(queries, expected)

    from server.app.core.config import settings
    from server.app.db.session import SessionLocal

    with SessionLocal() as session:
        # Preflight before any retrieval.  This is intentionally redundant with
        # the strict embedder so a missing model has one clear error code.
        require_embedding_model(session, args.tenant_id)
        context = _live_access_context(session, args.tenant_id, args.user_id)
        file_to_document_id, document_id_to_file = _fixture_document_map(
            session, args.tenant_id, expected
        )
        baseline_rankings, baseline_hash = _run_live_mode(
            session=session,
            context=context,
            mode=args.baseline_mode,
            queries=queries,
            file_to_document_id=file_to_document_id,
            document_id_to_file=document_id_to_file,
        )
        candidate_rankings, candidate_hash = _run_live_mode(
            session=session,
            context=context,
            mode=args.candidate_mode,
            queries=queries,
            file_to_document_id=file_to_document_id,
            document_id_to_file=document_id_to_file,
        )
        chunks, index_size = _live_chunk_health(
            session, document_id_to_file.keys()
        )
        import_latencies = _live_import_stage_latency_ms(
            session, document_id_to_file.keys()
        )
        report = build_evaluation_report(
            queries=queries,
            expected=expected,
            baseline_rankings=baseline_rankings,
            candidate_rankings=candidate_rankings,
            baseline_config_hash=baseline_hash,
            candidate_config_hash=candidate_hash,
            baseline_mode=args.baseline_mode,
            candidate_mode=args.candidate_mode,
            chunks=chunks,
            min_tokens=settings.chunk_min_tokens,
            max_tokens=settings.chunk_max_tokens,
            index_size=index_size,
            import_latency_ms=import_latencies,
        )
    json_path, markdown_path = write_reports(args.output, report)
    print(f"jsonReport={json_path}")
    print(f"markdownReport={markdown_path}")


if __name__ == "__main__":
    try:
        main()
    except (EvaluationInputError, EvaluationRuntimeError) as exc:
        raise SystemExit(str(exc)) from exc
