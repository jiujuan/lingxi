# Chunking Retrieval Evaluation Runbook

## Purpose and frozen dataset contract

Task 19 evaluates QA-only against Hybrid retrieval with a corpus that is
versioned in Git:

```text
server/tests/fixtures/chunking_eval/
├── corpus/
├── queries.jsonl
└── expected_evidence.jsonl
```

Do not edit, rename, or replace corpus files for a comparison run.  The JSON
report records a SHA-256 dataset hash over the ordered JSONL records; retain
that hash with every benchmark result.  `sourceSpan.anchorText` is the frozen,
exact evidence anchor used to match live candidate content across parser
locator implementations.  Runtime candidates still retain their native source
locator for citations.

The fixture includes all required scenarios: exact entity, section-limited
fact, cross-paragraph fact, table, code symbol, formula explanation, image
caption, a fact without QA coverage, and a permission-denied document.

## One-time evaluation tenant preparation

1. Use a dedicated tenant and upload every file in
   `server/tests/fixtures/chunking_eval/corpus/` with its exact filename.
2. Wait until all nine documents are parsed, indexed, and have active chunks.
3. Generate QA for the corpus **except** `qa-gap.md`; it intentionally tests
   retrieval of a chunk with no QA pair.
4. Give the selected evaluation user normal retrieval permissions and access to
   every fixture document **except** `restricted-policy.md`.  Do not grant an
   inherited role, department, or document permission that exposes it.
5. Configure an active default embedding model for the tenant.  The evaluator
   requires a real provider vector for each query and does not use fallback or
   synthetic embeddings.

Set an identity either in the environment or on the command line:

```powershell
$env:CHUNKING_EVAL_TENANT_ID = "<tenant-id>"
$env:CHUNKING_EVAL_USER_ID = "<user-id>"
```

## Run

From the repository root:

```powershell
.\.venv\Scripts\python.exe server/scripts/evaluate_chunking_retrieval.py `
  --queries server/tests/fixtures/chunking_eval/queries.jsonl `
  --expected server/tests/fixtures/chunking_eval/expected_evidence.jsonl `
  --baseline-mode qa-only `
  --candidate-mode hybrid `
  --output .data/chunking-eval `
  --tenant-id <tenant-id> `
  --user-id <user-id>
```

The command emits:

```text
.data/chunking-eval/chunking-evaluation.json
.data/chunking-eval/chunking-evaluation.md
```

Each report contains the frozen dataset hash, baseline/candidate retrieval
configuration hashes, Recall@5/10, MRR@10, nDCG@10, empty-result rate,
citation accuracy, duplicate-evidence rate, permission-leak rate, query
P50/P95 latency, chunk token distribution, tiny/oversized prose counts, QA
coverage, index-size signals, and import-stage P50/P95 latency.

`importLatencyMs` is specifically the duration of successful `TaskRun` stages
(`created_at` to `updated_at`) joined to the fixture documents' completed
`ImportJob` records.  It is not presented as a fabricated end-to-end upload
duration because the current schema has no full import-envelope timestamp.

## Failure handling

- A missing or inactive default embedding model exits non-zero with
  `EMBEDDING_MODEL_MISSING`.  No report is written and no fallback vector is
  generated.
- Missing fixture filenames in the tenant exit with
  `EVALUATION_CORPUS_NOT_INDEXED`.
- A fixture document that has not reached `READY` exits with
  `EVALUATION_CORPUS_NOT_READY`.
- An inactive/wrong-tenant user exits with `EVALUATION_USER_INVALID`.
- A retrieval snapshot without a stable configuration hash exits with
  `EVALUATION_CONFIG_HASH_MISSING` or
  `EVALUATION_CONFIG_HASH_INCONSISTENT`.

Correct the environment and re-run.  Do not compare a partial report, a
synthetic-vector result, or results from a changed fixture corpus.

## Acceptance interpretation

Use the frozen dataset result with the Task 19 quality gates:

| Gate | Required outcome |
|---|---|
| Hybrid Recall@10 | Not below QA-only; target >= 10% relative improvement |
| MRR@10 | Not below QA-only |
| Citation provenance accuracy | 100% |
| Oversized prose chunks | 0 |
| Empty-result rate | Improved or no worse |
| Top-K duplicate evidence | Below 10% |
| Permission leak rate | 0% |
| P95 query latency | Increase <= 30%; otherwise tune channel candidate K or defer rerank |

Archive the JSON and Markdown outputs together with the commit SHA and the two
configuration hashes.  If a result fails a gate, keep the report as evidence,
do not promote the candidate settings, and adjust the retrieval/chunking
configuration before repeating the same frozen evaluation.

## Task 21 offline capacity benchmark

Task 21 supplies a hermetic, versioned CPU/capacity and retrieval-regression
benchmark. It reads only `server/tests/fixtures/chunking_eval/benchmark_corpus`
and uses temporary in-memory SQLite databases to execute the production ORM
persistence methods plus `RetrievalService.retrieve()`. It does not contact an
external database, network service, worker, model provider, or vector index.

```powershell
.\.venv\Scripts\python.exe server/scripts/benchmark_chunking.py `
  --corpus server/tests/fixtures/chunking_eval/benchmark_corpus `
  --repeat 5 `
  --output .data/chunking-benchmark.json
```

Run from the repository root. Invalid input returns exit code `2` before a
report can be created. A gate failure also returns `2`, but only **after** the
complete, schema-valid JSON report has been written to `--output`. A zero exit
code means every offline gate passed. Threshold changes require an explicit
documented decision and fresh evidence.

### Report contract

The report schema version is `adaptive-chunking-benchmark/v1`. The following
names are stable report fields, not descriptive aliases:

```text
schemaVersion
measurement.clock / retrievalClock / unit / externalParserIncluded /
  networkIncluded / retrievalEnvironment
corpus.path / sourceDocumentCount / atomicBlockCount / pageCount / bytes / sha256
determinism.repeatCount / childHashSets / childHashSetStable
counts.parentCount / childCount / embeddingCount
stats.mergeCount / splitCount / oversizedCount / overlapChildCount
baselineWork.parseArtifactCount / legacyChunkRowCount
indexEstimate.rowPayloadBytes / embeddingVectorBytes /
  vectorIndexOverheadBytes / totalBytes
timings.legacyParsePersist.p50Ms / p95Ms
timings.adaptiveParsePersist.p50Ms / p95Ms / perMbMs / perPageMs
timings.qaOnlyPostTopKFusionCpuProxy.p50Ms / p95Ms
timings.hybridPostTopKFusionCpuProxy.p50Ms / p95Ms
timings.qaOnlyRetrieval.p50Ms / p95Ms
timings.hybridRetrieval.p50Ms / p95Ms
acceptance.determinismChildHashes / nfr003ChunkingCpu /
  postTopKFusionCpuProxy / nfr004Retrieval
acceptanceFailureReasons
```

`legacyParsePersist` is the baseline. It must retain the production legacy
`DocumentParseService` row/token semantics: raw parser-block content and
locator values, plus `_count_tokens(content)` from
`document_parse_service`. It is not permitted to normalize legacy content,
substitute `LocalTokenCounter`, use a projection multiplier, or report a
partial flat-row microbenchmark as a complete parse/persist envelope.

`adaptiveParsePersist` is the matching adaptive parse/persist envelope using
the production `ChunkingService`, `ChunkPolicy`, and persistence projection for
every emitted Parent and Child. The comparison must include equivalent parser
artifact and persistence-boundary work on both sides; it must not inflate the
legacy baseline.

Both timed paths invoke production
`DocumentParseService._replace_parse_outputs`: the legacy path reaches
`_write_legacy_chunks`, and the adaptive path reaches `_write_adaptive_chunks`.
The temporary SQLite transaction is rolled back after each individual timed
iteration, so warmup and sampling work cannot leave rows for later iterations.

`qaOnlyPostTopKFusionCpuProxy` and `hybridPostTopKFusionCpuProxy` time only
CPU work after deterministic, already ranked candidates have been limited to
the configured production channel caps. They intentionally exclude database,
vector-index, embedding, provider, and network latency.

`qaOnlyRetrieval` and `hybridRetrieval` time a fixed query sequence through the
complete production `RetrievalService.retrieve()` path: deterministic local
query embedding, production tokenization, scoped SQLite repository queries,
RRF/fusion, retrieval snapshots, and deterministic local reranking. Parent
hydration is disabled. `measurement.retrievalEnvironment` records this
boundary exactly.

`nfr004Retrieval` is the hermetic regression gate:
`hybridRetrieval.p95Ms <= qaOnlyRetrieval.p95Ms * 2.00`. This is a real local
request-path measurement, not a production-latency claim. It excludes
PostgreSQL execution plans, vector-index latency, remote embedding/reranking
providers, and network latency. Task 19's live end-to-end evaluator remains
required production-release evidence for those environments and its NFR-004
gate must still pass before promotion.

`embeddingCount` equals `childCount`. The index estimate assumes float32,
1,536-dimensional vectors and 64 bytes of index overhead per Child. It is
capacity-planning data, not a PostgreSQL index-size measurement.

### Frozen representative corpus

The corpus is versioned at
`server/tests/fixtures/chunking_eval/benchmark_corpus/manifest.json` and is
hashed in every report. It contains two source documents, six document/page
combinations, prose that crosses a merge boundary, an oversized prose block
that must split with overlap, a Markdown table, Python code, and independent
blocks for configured QA/Child Top-K channels.

The performance regression test asserts actual outcomes rather than merely
nonzero rows: `mergeCount > 0`, `splitCount > 0`,
`overlapChildCount > 0`, positive Parent/Child counts, and
`parentCount + childCount > atomicBlockCount`. This proves hierarchy expansion
as well as the required merge/split/overlap cases.

### Offline gates and failure evidence

All four gates are evaluated independently; failures never short-circuit later
gates. `acceptanceFailureReasons` retains every applicable reason, including a
determinism-only failure or simultaneous failures.

| Gate | Report field | Formula | Required result |
|---|---|---|---|
| Determinism | `determinismChildHashes` | Every non-empty sorted Child content-hash set is identical across all repeats. | `true` |
| NFR-003 | `nfr003ChunkingCpu` | `adaptiveParsePersist.p95Ms <= legacyParsePersist.p95Ms * 1.20` | `true` |
| Post-Top-K fusion CPU proxy | `postTopKFusionCpuProxy` | `hybridPostTopKFusionCpuProxy.p95Ms <= qaOnlyPostTopKFusionCpuProxy.p95Ms * 1.30` | `true` |
| NFR-004 local retrieval | `nfr004Retrieval` | `hybridRetrieval.p95Ms <= qaOnlyRetrieval.p95Ms * 2.00` | `true` |

The CLI validates the complete report before persisting it and before deciding
the exit code. Validation rejects obsolete timing names, a missing reason for
any failed gate, a failure reason attached to a passing gate, and any attempted
unknown gate. Preserve failed reports as evidence; do not promote the related
feature flag until the real measured stage is corrected.

Archive the JSON report with Git SHA, execution date/time, OS/Python version,
CPU model/core count, corpus SHA-256, effective policy/configuration hash, and
the Task 19 live-evaluation result.

### Failure/degradation drill evidence

Run the regression suite before changing a flag or promoting retrieval
configuration:

```powershell
.\.venv\Scripts\python.exe -m pytest server/tests/test_chunking_performance.py -q
```

| Injected failure | Required safe behavior | Evidence |
|---|---|---|
| Tokenizer unavailable | Parsing fails explicitly with `CHUNK_TOKENIZER_UNAVAILABLE`; no character-count fallback. | Service-level tokenizer regression test. |
| QA embedding succeeds; subsequent Child embedding times out | The adapter call sequence is QA then Child; job/document/`TaskRun` fail and all QA/Child partial vectors are rolled back. | `test_child_embedding_timeout_after_qa_success_rolls_back_all_vectors`. |
| Child retrieval query timeout | QA evidence remains available while only Child channels degrade. | Retrieval snapshot sets `chunkRetrievalDegraded=true`. |
| Parent hydration query failure | Winning Child quote/locator/citation remains usable and prompt receives Child-only context. | Hydration fallback regression test. |
| Reranker outage | Preserve three-candidate RRF order, then apply `final_top_k`; each final rerank score equals its fused score. | Reranker regression test. |
| Interrupted backfill handoff | Recovery is idempotent: no duplicate QA/embedding dispatch and no stale `RUNNING` `TaskRun`. | Durable-state regression in `server/tests/test_chunk_backfill.py`. |

Logs and snapshots used for drills may contain only IDs, hashes, counts,
durations, and reason codes. Never add source content, embeddings, prompt text,
or credentials to benchmark or degradation evidence.

## Task 22 local acceptance record (2026-08-01)

This section is the repository-local acceptance record for Task 22. It proves
the checked-in implementation and hermetic evidence below; it does not close
the staging or production release gates listed in "External release gates"
below.

The Task 22 executable logger/migration acceptance changes are committed as
`dc764b9` (`fix(observability): preserve logger state during migrations`).
The commands below ran in the shared, dirty worktree whose executable Task 22
files match that commit; unrelated user changes were deliberately left
unstaged. This record is worktree evidence, not an assertion that a clean
checkout has completed every external release gate.

### Local regression evidence

| Check | Command or environment | Result |
|---|---|---|
| Full backend regression | `.\.venv\Scripts\python.exe -m pytest server/tests -q -rs` | `740 passed, 3 skipped, 3 warnings` in `401.65s` |
| Chunking specialization | Task 22's 12-file Chunking command | `329 passed, 2 skipped` in `71.61s` |
| Parser baseline | Task 22 parser baseline command | `58 passed` in `20.19s` |
| Task 21 performance/degradation tests | `.\.venv\Scripts\python.exe -m pytest server/tests/test_chunking_performance.py -q` | `17 passed` in `62.30s` |
| Logging and Alembic regressions | `test_observability_infra.py` and `test_knowledge_classification.py` | `28 passed, 3 warnings` in `18.45s` |
| Static tooling | `pyproject.toml`, repository config search, and `.venv\Scripts` | No Ruff or Mypy configuration or executable is present. This is recorded as an absent project gate, not a passing lint/type check. |

The full-suite skips are environment-specific integration checks, not converted
test failures:

| Skipped test | Reason |
|---|---|
| `test_embedding_task.py:900` | `LINGXI_TEST_POSTGRES_URL` is not configured for the PostgreSQL lock integration. |
| `test_hybrid_chunk_retrieval_integration.py:424` | `LINGXI_TEST_CELERY_BROKER_URL` is not configured for the local Celery worker integration. |
| `test_hybrid_chunk_retrieval_integration.py:534` | `LINGXI_TEST_POSTGRES_URL` is not configured for the PostgreSQL integration. |

The warnings were FastAPI's `TestClient` deprecation notice and Alembic's
`prepend_sys_path` `path_separator` deprecation notice. They do not change the
pass/fail result and should be addressed independently of this rollout.

### Migration and operator-entry evidence

The migration was exercised only against a unique local SQLite file under the
ignored `.data` directory:

```powershell
$env:DATABASE_URL = "sqlite+pysqlite:///<unique-local-path>"
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade 0006_user_role_role_id_index
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe current
```

The final output was `0007_adaptive_chunking (head)`. Compatibility of legacy
rows and migration idempotence is also covered by the passing migration tests.
This SQLite roundtrip is schema evidence only; it does not prove PostgreSQL
pgvector, FTS, or query-plan behavior.

The backfill entry point is verified as a module command:

```powershell
.\.venv\Scripts\python.exe -m server.scripts.backfill_adaptive_chunks --help
```

For a production backfill, record the actual values in the release dossier,
run a dry run first, and use the explicit confirmation form:

```powershell
.\.venv\Scripts\python.exe -m server.scripts.backfill_adaptive_chunks `
  --tenant-id <tenant-id> `
  --to-chunker-version <chunker-version> `
  --batch-size <batch-size> `
  --execution-id <execution-id> `
  --operator-id <operator-id> `
  --reason "adaptive chunking rollout" `
  --rebuild-qa `
  --rebuild-embedding `
  --confirm-production
```

### Task 21 benchmark decision and evidence

The current hermetic report is `.data/chunking-benchmark.json`, schema
`adaptive-chunking-benchmark/v1`, with report SHA-256
`5DDEAAE5116D753B5F596CC69462CC3F226B0BF6C233DBBB3FBA89A6A9967F26`
and corpus SHA-256
`7dd8742013d20e0e7a770025a0045b62242ee4d5e0414463b6a5a63bcf6192ce`.
It was regenerated with `--repeat 5` on 2026-08-01 and reports stable Child
hash sets, 29 Child chunks, and no acceptance failure reasons.

| Measurement | QA-only P50/P95 | Hybrid P50/P95 | Result |
|---|---:|---:|---|
| Full local retrieval path | `57.3384 / 65.0697 ms` | `103.5504 / 121.37496 ms` | P50 `1.806x`, P95 `1.865x`; local NFR-004 passes at `<= 2.00x` |
| Parse/persist CPU | legacy `281.25 / 310.9375 ms` | adaptive `125.0 / 132.8125 ms` | NFR-003 passes |

The Task 21 local NFR-004 threshold is deliberately `2.00x`, rather than the
production `<=30%` requirement. Its deterministic in-memory SQLite path adds
four-channel Python/ORM work but excludes PostgreSQL query planning, pgvector,
remote embedding/reranking, and network latency. The `2.00x` bound therefore
detects large local request-path regressions without making a production
latency assertion. The measured local P95 increase is `86.5%`, which is why it
must never be substituted for the production gate.

### External release gates

The following Task 22 requirements remain release-blocking until real
environment evidence is frozen and attached to the release record:

| Gate | Required evidence |
|---|---|
| Task 19 quality evaluation | Frozen JSON and Markdown from the real provider evaluator, including dataset hash, commit SHA, baseline/candidate config hashes, Recall/MRR/nDCG, citation accuracy, tiny-ratio comparison, duplicate rate, and empty-result rate. |
| PostgreSQL behavior | Temporary PostgreSQL upgrade/downgrade, pgvector dimension/index checks, FTS checks, and captured `EXPLAIN` plans showing scoped Top-K behavior. |
| NFR-004 production latency | Real staging or production QA-only versus Hybrid P50/P95; Hybrid P95 increase must be `<=30%`. |
| Integration environment | The skipped PostgreSQL lock/retrieval and local Celery worker tests must run with their documented environment variables. |
| Tenant rollout control | The application currently exposes process-global flags only; it has no tenant targeting or percentage allocator. A control-plane cohort mechanism or a per-tenant rollout implementation is required before `5%`/`25%`/`50%`/`100%` promotion can begin. |

### Release dossier, rollout, and rollback

Before promotion, archive the migration revision
`0007_adaptive_chunking`, deployed commit SHA, chunker name/version/config hash,
tokenizer identity/version, effective flag values, backfill execution ID,
dashboard links, benchmark/evaluator artifacts, and the operator who approved
each stage. The `/metrics` dashboard must at least cover:

```text
lingxi_chunking_duration_seconds
lingxi_chunk_tokens
lingxi_chunk_tiny_total
lingxi_chunk_oversized_total
lingxi_chunk_merge_total
lingxi_chunk_split_total
lingxi_qa_provenance_validation_failure_total
lingxi_qa_chunk_coverage_ratio
lingxi_embedding_targets_total
lingxi_retrieval_candidates_total
lingxi_retrieval_channel_hit_ratio
lingxi_retrieval_dedup_ratio
lingxi_retrieval_latency_seconds
lingxi_retrieval_degraded_total
```

Apply stages in order, retaining the evidence from each completed stage:

1. Upgrade schema with all flags at their default off values:
   `CHUNKING_MODE=legacy`, `QA_STRICT_PROVENANCE_ENABLED=false`,
   `CHUNK_INDEXING_ENABLED=false`, `HYBRID_CHUNK_RETRIEVAL_ENABLED=false`, and
   `PARENT_CONTEXT_ENABLED=false`.
2. Run adaptive shadow comparison, then adaptive write with QA-only read.
3. Enable strict provenance, then Chunk indexing, then Hybrid shadow.
4. Do not enable process-global Hybrid for a percentage rollout. First supply
   and validate a tenant-scoping control plane or per-tenant feature flag; then
   promote at `5%`, `25%`, `50%`, and `100%`, observing a full business peak
   after every promotion.
5. Enable Parent hydration only after the Hybrid stage is stable.

Stop immediately for any permission leak, provenance validation error,
quality-regression gate failure, Hybrid P95 increase above `30%`, sustained
retrieval degradation, unsafe backfill state, or alerting/dashboard gap.
Roll back by setting the following values, redeploying through the normal
platform procedure, and preserving rows for Active-version recovery rather
than deleting data:

```powershell
$env:PARENT_CONTEXT_ENABLED = "false"
$env:HYBRID_CHUNK_RETRIEVAL_ENABLED = "false"
$env:CHUNK_INDEXING_ENABLED = "false"
$env:QA_STRICT_PROVENANCE_ENABLED = "false"
$env:CHUNKING_MODE = "legacy"
```

Do not promote from this local record alone. Attach the external evidence above
to the release dossier before enabling a later rollout stage.
