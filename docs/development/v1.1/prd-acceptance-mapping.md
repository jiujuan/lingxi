# V1.1 PRD Acceptance Mapping

| PRD Area | Acceptance Requirement | Evidence |
| --- | --- | --- |
| Login and RBAC | Admin and employee can authenticate; protected endpoints enforce permissions. | `server\tests\test_auth_rbac.py`, full suite 67 passed |
| Knowledge import | Admin can create import job, bind file, parse, split QA, embed, and reach READY. | `server\tests\e2e\test_v1_1_release_e2e.py::test_knowledge_import_to_ready_chat_citation_and_openai_api` |
| Document security | Unsafe `object_key` values are rejected. | `server\tests\security\test_secret_redaction.py::test_object_key_path_traversal_and_windows_paths_are_rejected` |
| Permission isolation | Unauthorized private documents do not enter retrieval, prompt, answer, or citations. | `server\tests\e2e\test_v1_1_release_e2e.py::test_permission_isolation_refusal_and_api_key_lifecycle`, `server\tests\test_retrieval_service.py` |
| Web Chat | Employee can ask a question and receive streaming answer events. | `server\tests\test_chat_sse.py`, `web\admin\tests\t11_chat_playwright.py` |
| Citations | Answers include citations; source drawer and retrieval explanation are available. | `server\tests\test_citations_and_explanation.py`, `web\admin\tests\t12_citation_explanation_playwright.py` |
| Knowledge missed/refusal | Insufficient knowledge returns fixed refusal text and no citation. | `server\tests\test_chat_sse.py::test_chat_low_confidence_refuses_without_citation`, E2E release test |
| OpenAI-compatible API | Non-streaming and streaming `/v1/chat/completions` work with citations and request_id. | `server\tests\test_openai_compatible_api.py`, E2E release test |
| API Key lifecycle | API Key create, disable, rotate, scope, and rate-limit behavior is enforced. | `server\tests\test_api_keys.py`, E2E release test, `web\admin\tests\t13_api_key_playwright.py` |
| Observability | request_id, run_id, and task_run_id can be used for troubleshooting. | `server\tests\e2e\test_v1_1_release_e2e.py::test_logs_link_request_run_and_task_identifiers`, `web\admin\tests\t17_release_playwright.py` |
| Dashboard | Summary, ingestion health, QA health, recent tasks, and risk events render. | `server\tests\test_dashboard_settings.py`, `web\admin\tests\t17_release_playwright.py` |
| Settings | Settings read/save, validation, high-risk confirmation, and audit logging work. | `server\tests\test_dashboard_settings.py`, `web\admin\tests\t17_release_playwright.py` |
| Secret handling | API Key, model key, Authorization header, and secret snapshots are redacted. | `server\tests\test_log_redaction.py`, `server\tests\security\test_secret_redaction.py` |
| Prompt guardrails | Prompt states reference/user content is untrusted and cannot override instructions. | `server\tests\security\test_prompt_guardrails.py` |
| Browser acceptance | Desktop and mobile widths render without horizontal overflow. | Playwright screenshots in `docs/development/v1.1/acceptance/` |
| Performance baseline | Retrieval and chat first-token baselines are recorded. | `scripts\perf\retrieval_baseline.py`, `scripts\perf\chat_first_token_baseline.py` |
| Private deployment | Compose includes PostgreSQL, Redis, API, Worker, Web Admin, shared storage, health checks. | `deploy\docker-compose.yml`, `docs\development\v1.1\release-checklist.md` |

