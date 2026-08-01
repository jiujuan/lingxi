# Task 21 Retrieval NFR-004 Evidence Design

## Goal

Make the Task 21 hermetic benchmark produce repeatable P50/P95 evidence for
the real `RetrievalService.retrieve()` request path and evaluate NFR-004:

```text
hybridRetrieval.p95Ms <= qaOnlyRetrieval.p95Ms * 2.00
```

The benchmark must not claim a production PostgreSQL, vector-index, model
provider, or network latency result.

## Scope

The benchmark will create a representative QA and Child evidence set in its
existing in-memory SQLite harness. It will build two `RetrievalService`
instances with the same fixed configuration and deterministic local
dependencies:

- QA-only service: `hybrid_chunk_retrieval_enabled=False`.
- Hybrid service: `hybrid_chunk_retrieval_enabled=True`.

Each timed sample will call `retrieve()` for a fixed query sequence. The
measurement includes query embedding, tokenization, repository search, RRF,
snapshot creation, and local rerank fallback. It excludes remote dependencies
by injecting a deterministic query embedder and a local no-op reranker, and it
does not enable Parent hydration.

## Report Contract

The report will retain the parse/persist timings and add:

```text
measurement.retrievalEnvironment
timings.qaOnlyRetrieval.p50Ms / p95Ms
timings.hybridRetrieval.p50Ms / p95Ms
acceptance.nfr004Retrieval
```

`measurement.retrievalEnvironment` will state that the result uses local
SQLite and deterministic local embedding/reranking, and explicitly excludes
remote provider, PostgreSQL, vector-index, and network latency.

The existing post-Top-K fusion CPU proxy remains a diagnostic field. It is not
the NFR-004 gate.

## Failure Semantics

The report validator will require finite, non-negative retrieval values and a
positive QA-only P95 baseline. A hybrid P95 above 130 percent of QA-only P95
will set `nfr004Retrieval` to false, add an NFR-004 failure reason, write the
complete report, and make the CLI return exit code 2.

## Verification

Tests will first assert the new report fields, the actual request-path
invocation, validation of NFR-004 reasons, and CLI persistence on gate failure.
The completion checks will run the Task 21 performance tests, focused retrieval
service regressions, the backfill recovery test, and the five-repeat benchmark.
The runbook will distinguish this hermetic regression gate from Task 19's live
production-release evidence.
