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
