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
