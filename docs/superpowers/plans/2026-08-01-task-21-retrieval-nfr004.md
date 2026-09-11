# Task 21 Retrieval NFR-004 Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add hermetic real-request P50/P95 retrieval evidence and enforce the
Task 21 NFR-004 30-percent Hybrid latency gate.

**Architecture:** Keep the parse/persist benchmark unchanged. Add an isolated
in-memory SQLite retrieval fixture that seeds authorized Documents, QA pairs,
and Child chunks, then measures `RetrievalService.retrieve()` in QA-only and
Hybrid modes with deterministic local embedding and reranking dependencies.
The report distinguishes this local regression gate from Task 19's live
production evidence.

**Tech Stack:** Python, pytest, SQLAlchemy SQLite, `perf_counter`, existing
`RetrievalService` and `RetrievalRepository`.

---

## File Structure

| Path | Responsibility |
|---|---|
| `server/scripts/benchmark_chunking.py` | Seed the local retrieval harness, time both real service modes, validate and gate the report. |
| `server/tests/test_chunking_performance.py` | Lock the report contract, true request-path execution, NFR-004 failure behavior, and CLI persistence. |
| `docs/design/v1.1/chunk/evaluation-runbook.md` | Define the local measurement boundary and relationship to Task 19. |

### Task 1: Lock the real retrieval report contract with failing tests

**Files:**
- Modify: `server/tests/test_chunking_performance.py`
- Reference: `server/app/services/retrieval_service.py:81`

- [ ] **Step 1: Add a report-contract test that requires real retrieval timing and NFR-004.**

```python
def test_offline_benchmark_reports_real_retrieval_timings_and_nfr004(monkeypatch):
    import server.scripts.benchmark_chunking as benchmark
    from server.app.services.retrieval_service import RetrievalService

    calls = 0
    original = RetrievalService.retrieve

    def trace_retrieve(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

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
```

- [ ] **Step 2: Run the contract test and confirm it fails because the existing proxy benchmark never invokes `retrieve()`.**

Run: `.\.venv\Scripts\python.exe -m pytest server/tests/test_chunking_performance.py::test_offline_benchmark_reports_real_retrieval_timings_and_nfr004 -q`

Expected: FAIL with `calls == 0` or a missing `qaOnlyRetrieval` report field.

- [ ] **Step 3: Add failing NFR-004 gate and report-validation tests.**

```python
def test_acceptance_reports_nfr004_failure_independently():
    from server.scripts.benchmark_chunking import evaluate_acceptance

    outcome = evaluate_acceptance(
        baseline_parse_p95_ms=100.0,
        candidate_chunk_p95_ms=100.0,
        baseline_proxy_p95_ms=50.0,
        candidate_proxy_p95_ms=50.0,
        baseline_retrieval_p95_ms=10.0,
        candidate_retrieval_p95_ms=13.01,
        child_hash_sets=[("a",), ("a",)],
    )

    assert outcome["acceptance"]["nfr004Retrieval"] is False
    assert outcome["failureReasons"][-1] == (
        "NFR-004 failed: hybrid retrieval P95 exceeds QA-only retrieval P95 x 1.30"
    )
```

- [ ] **Step 4: Run the NFR-004 test and confirm it fails because `evaluate_acceptance()` lacks retrieval inputs and gate output.**

Run: `.\.venv\Scripts\python.exe -m pytest server/tests/test_chunking_performance.py::test_acceptance_reports_nfr004_failure_independently -q`

Expected: FAIL with an unexpected keyword argument for
`baseline_retrieval_p95_ms`.

### Task 2: Implement the hermetic real request-path benchmark

**Files:**
- Modify: `server/scripts/benchmark_chunking.py`
- Test: `server/tests/test_chunking_performance.py`
- Reference: `server/app/repositories/retrieval_repo.py:101`

- [ ] **Step 1: Add a retrieval-only SQLite harness that uses production repository search.**

```python
@dataclass
class _RetrievalHarness:
    session: Session
    context: AccessContext
    queries: Sequence[str]

    def close(self) -> None:
        self.session.close()


def _new_retrieval_harness() -> _RetrievalHarness:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session = sessionmaker(bind=engine, autoflush=False, autocommit=False)()
    Base.metadata.create_all(bind=engine)
    identity = seed_identity_data(session)
    tenant_id = identity["tenant"].id
    evidence = (
        ("refund", "退款审批需要主管确认", [1.0, 0.0, 0.0, 0.0]),
        ("invoice", "发票退款需要先红冲发票", [0.0, 1.0, 0.0, 0.0]),
    )
    for index, (topic, content, vector) in enumerate(evidence):
        document = Document(
            tenant_id=tenant_id, title=f"{topic} benchmark",
            file_name=f"{topic}.md", file_type="MARKDOWN",
            mime_type="text/markdown", file_size=len(content.encode("utf-8")),
            object_key=f"benchmark/{topic}.md", checksum=f"benchmark-{topic}",
            status=DocumentStatus.READY,
        )
        session.add(document)
        session.flush()
        session.add(DocumentAccessRule(
            tenant_id=tenant_id, document_id=document.id,
            subject_type=DocumentAccessSubjectType.ALL_AUTHENTICATED,
        ))
        chunk = DocumentChunk(
            tenant_id=tenant_id, document_id=document.id, chunk_index=index,
            title_path=[topic], content=content, token_count=4,
            source_locator={"benchmark": topic},
            source_locators=[{"benchmark": topic}],
            content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            embedding=vector, search_text=content, status="ACTIVE",
            chunk_level="CHILD",
        )
        session.add(chunk)
        session.flush()
        session.add(QaPair(
            tenant_id=tenant_id, document_id=document.id, chunk_id=chunk.id,
            pair_index=index, question=content, answer=content, quote=content,
            question_embedding=vector, search_text=content, status="ACTIVE",
        ))
    session.commit()
    context = AccessContext(
        tenant_id=tenant_id, user_id=identity["users"]["employee"].id,
        department_id=identity["departments"]["support"].id,
        role_ids=[identity["roles"]["employee"].id],
        permissions={"DOCUMENT_READ"}, role_codes={"EMPLOYEE"},
    )
    return _RetrievalHarness(
        session=session, context=context,
        queries=tuple(content for _topic, content, _vector in evidence),
    )
```

Import `AccessContext`, `Document`, `DocumentAccessRule`,
`DocumentAccessSubjectType`, `DocumentStatus`, `DocumentChunk`, `QaPair`, and
`seed_identity_data` at module level. Do not monkeypatch any
`RetrievalRepository` search method.

- [ ] **Step 2: Add deterministic local dependencies and wall-clock sampling.**

```python
class _DeterministicReranker:
    def rerank(self, _question, candidates):
        for candidate in candidates:
            candidate.rerank_score = candidate.fused_score
        return candidates


def _retrieval_service(harness, *, hybrid: bool) -> RetrievalService:
    service = RetrievalService(
        harness.session,
        config=replace(get_retrieval_config(), final_top_k=5),
        reranker=_DeterministicReranker(),
        hybrid_chunk_retrieval_enabled=hybrid,
        parent_context_enabled=False,
    )
    service._embed_query = lambda _tenant_id, _question: [1.0, 0.0, 0.0, 0.0]
    return service


def _measure_retrieval_ms(service, harness) -> float:
    started = perf_counter()
    for query in harness.queries:
        service.retrieve(harness.context, query)
    return (perf_counter() - started) * 1000
```

Leave `JiebaTokenizer` and all repository searches unmodified so the timed
path includes production tokenization, scoped SQLite queries, RRF, snapshots,
and local reranking. Do not enable Parent hydration.

- [ ] **Step 3: Extend `run_benchmark()` and the report schema.**

```python
qa_retrieval_samples.append(
    _measure_retrieval_ms(_retrieval_service(retrieval_harness, hybrid=False), retrieval_harness)
)
hybrid_retrieval_samples.append(
    _measure_retrieval_ms(_retrieval_service(retrieval_harness, hybrid=True), retrieval_harness)
)

acceptance_outcome = evaluate_acceptance(
    baseline_parse_p95_ms=legacy_timing["p95Ms"],
    candidate_chunk_p95_ms=adaptive_timing["p95Ms"],
    baseline_proxy_p95_ms=qa_proxy_timing["p95Ms"],
    candidate_proxy_p95_ms=hybrid_proxy_timing["p95Ms"],
    baseline_retrieval_p95_ms=qa_retrieval_timing["p95Ms"],
    candidate_retrieval_p95_ms=hybrid_retrieval_timing["p95Ms"],
    child_hash_sets=child_hash_sets,
)
```

Add `qaOnlyRetrieval` and `hybridRetrieval` P50/P95 fields, the documented
`measurement.retrievalEnvironment`, and `acceptance.nfr004Retrieval`. Keep
the post-Top-K proxy fields as diagnostics. Update
`validate_benchmark_report()` so timing names, acceptance names, accepted
failure prefixes, and required measurement fields match the expanded contract.

The NFR-004 branch in `evaluate_acceptance()` must reject non-finite values,
reject a non-positive QA-only P95, and fail only when Hybrid P95 is greater
than QA-only P95 times `1.30`; it must retain other independent failure
reasons.

- [ ] **Step 4: Run the new focused tests and make them pass.**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  server/tests/test_chunking_performance.py::test_offline_benchmark_reports_real_retrieval_timings_and_nfr004 `
  server/tests/test_chunking_performance.py::test_acceptance_reports_nfr004_failure_independently -q
```

Expected: PASS.

- [ ] **Step 5: Update existing report and CLI tests to assert NFR-004 instead of forbidding it.**

Update timing, acceptance, invalid-reason, and CLI tests to include
`qaOnlyRetrieval`, `hybridRetrieval`, and `nfr004Retrieval`. Preserve the
test that a failed gate writes its complete, schema-valid report before the
CLI returns exit code 2; make its fixture include a valid NFR-004 result.

- [ ] **Step 6: Run the full Task 21 performance module.**

Run: `.\.venv\Scripts\python.exe -m pytest server/tests/test_chunking_performance.py -q`

Expected: PASS.

### Task 3: Document the evidence boundary and complete acceptance

**Files:**
- Modify: `docs/design/v1.1/chunk/evaluation-runbook.md`
- Modify: `server/tests/test_chunking_performance.py` only if verification exposes a regression

- [ ] **Step 1: Replace the offline-proxy-only wording in the runbook.**

List the two retrieval timings and `nfr004Retrieval` under the stable report
contract. State that the local gate measures full `RetrievalService.retrieve()`
against SQLite with deterministic local embedding/reranking and no Parent
hydration. State explicitly that Task 19 remains required production-release
evidence for PostgreSQL/vector-index/provider/network latency.

- [ ] **Step 2: Run focused retrieval and recovery regressions.**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest `
  server/tests/test_retrieval_service.py `
  server/tests/test_chunk_backfill.py::test_retry_recovers_interrupted_follow_up_dispatch_without_rescheduling_qa -q
```

Expected: PASS.

- [ ] **Step 3: Run the five-repeat benchmark and retain its JSON evidence.**

Run:

```powershell
.\.venv\Scripts\python.exe server/scripts/benchmark_chunking.py `
  --corpus server/tests/fixtures/chunking_eval/benchmark_corpus `
  --repeat 5 `
  --output .data/chunking-benchmark.json
```

Expected: exit code 0, stable Child hashes, and
`acceptance.nfr004Retrieval == true`. If the gate is false, keep the written
report, tune the implementation without lowering the 1.30 threshold, and
repeat this command.

- [ ] **Step 4: Review and submit only Task 21 files after fresh verification.**

Run:

```powershell
git diff --check
git diff -- server/scripts/benchmark_chunking.py server/tests/test_chunking_performance.py `
  server/tests/fixtures/chunking_eval/benchmark_corpus/manifest.json `
  docs/design/v1.1/chunk/evaluation-runbook.md
```

Then stage only the Task 21 implementation, tests, fixture, and runbook:

```powershell
git add -- server/scripts/benchmark_chunking.py `
  server/tests/test_chunking_performance.py `
  server/tests/fixtures/chunking_eval/benchmark_corpus `
  docs/design/v1.1/chunk/evaluation-runbook.md
git commit -m "perf(chunking): benchmark capacity and degradation paths"
git push origin feat/adaptive-hierarchical-chunk
```

Do not stage unrelated pre-existing changes.
