# V1.1 Known Limitations

## Deployment Verification

- Docker CLI is not installed on this workstation, so `docker compose up` smoke testing was not executed locally.
- `deploy/docker-compose.yml` has been updated with migration startup, health checks, and shared object storage. Run the smoke commands in `release-checklist.md` on a Docker-capable host before seed-customer handoff.

## Product Scope

- GraphRAG, multi-hop graph reasoning, IM integrations, Widget SDK, customer-service tickets, and SaaS billing are outside V1.1.
- Current permission model is document-level RBAC. Paragraph-level ABAC is not implemented.
- Current frontend is a lightweight custom React admin app. It does not yet use Ant Design/ProComponents even though design docs mention that as a target stack.

## Retrieval and Model Behavior

- Retrieval baseline uses the in-repo deterministic fake provider and in-memory test dataset; production latency depends on PostgreSQL, pgvector indexes, model provider latency, and deployment resources.
- Chat first-token baseline is measured through FastAPI TestClient with the fake provider; it is useful as a regression baseline, not a production SLA.
- Provider adapters for OpenAI-compatible, Ollama, Claude, and internal gateway share the internal adapter contract. Native provider-specific public API compatibility endpoints are not part of V1.1.

## Operations

- Log retention settings are persisted, but physical archival/deletion jobs are not implemented in V1.1.
- Dashboard metrics are MVP operational metrics, not a BI/reporting system.
- SSE reverse-proxy behavior still needs to be smoke-tested in the final customer deployment topology.

