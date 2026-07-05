# V1.1 Release Checklist

## Release Scope

- Version: V1.1 MVP
- Date: 2026-07-05
- Scope: enterprise knowledge import, permission-filtered retrieval, Web Chat with citations, OpenAI-compatible API, API Key management, observability, dashboard, settings, and private deployment assets.

## Automated Verification

| Gate | Command | Result |
| --- | --- | --- |
| Backend full test suite | `python -m pytest server\tests` | 67 passed |
| E2E and security hardening | `python -m pytest server\tests\e2e server\tests\security` | 7 passed |
| Frontend production build | `npm run build` in `web/admin` | passed |
| Browser acceptance | `python web\admin\tests\t09_knowledge_playwright.py; python web\admin\tests\t11_chat_playwright.py; python web\admin\tests\t12_citation_explanation_playwright.py; python web\admin\tests\t13_api_key_playwright.py; python web\admin\tests\t17_release_playwright.py` | passed |
| Retrieval performance baseline | `python scripts\perf\retrieval_baseline.py 10` | p50 1.268 ms, p95 4.813 ms, failureRate 0.0% |
| Chat first-token baseline | `python scripts\perf\chat_first_token_baseline.py 5` | p50 23.988 ms, p95 75.817 ms, failureRate 0.0% |

## Browser Evidence

Screenshots are stored under `docs/development/v1.1/acceptance/`.

- Knowledge center: `t09-knowledge-desktop.png`, `t09-knowledge-mobile.png`
- Chat: `t11-chat-desktop.png`, `t11-chat-mobile.png`
- Citation and explanation: `t12-citation-desktop.png`, `t12-citation-mobile.png`
- API Key: `t13-api-key-desktop.png`, `t13-api-key-mobile.png`
- Dashboard: `t17-dashboard-desktop.png`, `t17-dashboard-mobile.png`
- Logs: `t17-logs-desktop.png`, `t17-logs-mobile.png`
- Settings: `t17-settings-desktop.png`, `t17-settings-mobile.png`

## Docker Compose Private Deployment Check

`deploy/docker-compose.yml` includes:

- PostgreSQL with pgvector image.
- Redis.
- API container with `alembic upgrade head` before `uvicorn`.
- Worker container sharing the same object storage volume as API.
- Web Admin container.
- Health checks for PostgreSQL, Redis, API, and Web Admin.
- Shared `object_storage` volume for local object storage.

Smoke commands for a machine with Docker installed:

```powershell
docker compose -f deploy\docker-compose.yml up --build -d
docker compose -f deploy\docker-compose.yml ps
curl http://127.0.0.1:8000/health
docker compose -f deploy\docker-compose.yml down
```

Local environment note: Docker CLI is not installed on this machine, so container startup could not be executed here. The attempted command was `docker compose -f deploy\docker-compose.yml config`, which failed because `docker` was not found.

## Release Gates

- [x] Backend tests pass.
- [x] E2E and security tests pass.
- [x] Frontend build passes.
- [x] Desktop and mobile browser acceptance passes.
- [x] Performance baseline scripts produce P50, P95, and failure rate.
- [x] Compose deployment file includes required services, health checks, migration startup, and shared object storage.
- [x] Known limitations documented.

## Go/No-Go Recommendation

Go for internal seed-customer trial after Docker smoke is run on a host with Docker installed.

