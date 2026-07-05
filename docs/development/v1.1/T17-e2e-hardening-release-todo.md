# T17 端到端硬化、浏览器验证与试点交付

## 任务状态

- 状态：DONE_WITH_ENV_LIMITATION
- 完成任务进度：95%
- 优先级：P0
- 预计范围：中

## Task 目标

完成 V1.1 MVP 的端到端验收、安全回归、性能基线、浏览器验证和私有部署交付检查，确保系统达到种子客户试点标准。

## 实现功能

- 端到端测试数据和样本文档集。
- 核心 E2E：登录、上传、解析、QA、Embedding、READY、Chat、引用、OpenAI API。
- 权限隔离 E2E：无权文档不进入召回、Prompt、回答和引用。
- 知识不足拒答 E2E。
- API Key 创建、调用、禁用、轮换 E2E。
- 日志排障 E2E：request_id、run_id、task_run_id 串联。
- Playwright 桌面和移动宽度浏览器验证。
- SSE 在本地反向代理或 Docker Compose 下验证。
- 安全回归：Secret 脱敏、object_key 路径穿越、权限过滤、Prompt 约束。
- 性能基线脚本：混合检索 P95、首字响应 P95、文档列表 P95。
- Docker Compose 私有部署检查。
- PRD 验收清单映射到测试证据。
- 发布检查文档和已知限制清单。

## 修改或增加文件

- `server/app/tests/e2e/test_knowledge_import_to_chat.py`
- `server/app/tests/e2e/test_permission_isolation.py`
- `server/app/tests/e2e/test_openai_compatible_api.py`
- `server/app/tests/security/test_secret_redaction.py`
- `server/app/tests/security/test_prompt_guardrails.py`
- `web/src/tests/e2e/full-knowledge-flow.spec.ts`
- `web/src/tests/e2e/permission-isolation.spec.ts`
- `web/src/tests/e2e/mobile-chat.spec.ts`
- `scripts/perf/retrieval_baseline.py`
- `scripts/perf/chat_first_token_baseline.py`
- `docs/development/v1.1/release-checklist.md`
- `docs/development/v1.1/prd-acceptance-mapping.md`
- `docs/development/v1.1/known-limitations.md`

## 不修改范围

- 不新增 V1.1 范围外产品功能。
- 不做 GraphRAG、IM 深度接入、Widget SDK、客服工单或 SaaS 计费。
- 不以测试绕过真实权限校验。
- 不把性能优化扩大为架构替换。
- 不在此任务中重构前面已完成模块，除非阻塞验收。

## 涉及其它 Task

- 依赖 T01-T16 全部核心能力。
- 反向验证 T03/T10 的权限过滤。
- 反向验证 T11/T12 的引用和拒答。
- 反向验证 T13/T14 的 API Key 和 OpenAI 兼容接口。
- 反向验证 T15/T16 的日志、指标和设置。

## 测试策略

- 后端 E2E 使用固定租户、部门、角色、用户和样本文档。
- 前端 E2E 覆盖桌面和移动宽度。
- 安全测试覆盖权限、Secret、路径穿越、Prompt 越权指令。
- 性能测试记录 P50、P95、失败率和测试数据规模。
- Docker Compose 环境跑通 smoke test。
- 所有失败案例保留 request_id、run_id 或 task_run_id 作为证据。

## 长任务链路验收策略

从空环境启动 Docker Compose，初始化数据后以管理员上传样本文档并等待 READY；以员工身份提问获得带引用回答；以另一个无权员工提问确认无法召回该文档；以 API Key 调用 OpenAI 兼容接口确认返回引用；最后通过日志页用 request_id、run_id、task_run_id 完成排障追踪。

## 验收功能清单

- [ ] Docker Compose 可启动 PostgreSQL、Redis、后端、Worker 和前端。
- [x] 登录和权限初始化通过。
- [x] 文档上传到 READY 的完整链路通过。
- [x] Chat 有答案问题返回流式回答和引用。
- [x] Chat 无答案问题返回知识不足拒答。
- [x] 无权文档不进入召回、Prompt、回答或引用。
- [x] OpenAI 兼容 API 流式和非流式均通过。
- [x] API Key 禁用和轮换行为正确。
- [x] 日志页可按 request_id、run_id、task_run_id 排障。
- [x] Secret 脱敏和路径安全测试通过。
- [x] 桌面和移动宽度浏览器验证通过。
- [x] 性能基线记录核心指标。
- [x] PRD 验收清单有测试证据映射。
- [x] 发布检查和已知限制文档完成。

## 验收结果

- 已完成 T17 自动化验收、硬化测试、性能基线、浏览器验证和交付文档。
- 新增后端 E2E：
  - `server/tests/e2e/test_v1_1_release_e2e.py`
  - 覆盖文档上传到 READY、Chat 引用、OpenAI 兼容流式/非流式、权限隔离、拒答、API Key 禁用/轮换、request_id/run_id/task_run_id 日志排障。
- 新增安全回归：
  - `server/tests/security/test_secret_redaction.py`
  - `server/tests/security/test_prompt_guardrails.py`
  - 覆盖 Secret 脱敏、Authorization 脱敏、object_key 路径安全、Prompt 越权指令约束。
- 新增性能基线脚本：
  - `scripts/perf/retrieval_baseline.py`
  - `scripts/perf/chat_first_token_baseline.py`
- 新增浏览器验收脚本：
  - `web/admin/tests/t17_release_playwright.py`
  - 覆盖 Dashboard、日志排障、系统设置桌面和移动宽度。
- 更新 `deploy/docker-compose.yml`：
  - API 启动执行 `alembic upgrade head`。
  - PostgreSQL、Redis、API、Web Admin healthcheck。
  - API 与 Worker 共享 `object_storage` volume。
  - JWT/Secret 加入开发默认值，仍可由 `.env` 覆盖。
- 新增交付文档：
  - `docs/development/v1.1/release-checklist.md`
  - `docs/development/v1.1/prd-acceptance-mapping.md`
  - `docs/development/v1.1/known-limitations.md`
- 验证命令：
  - `python -m pytest server\tests\e2e server\tests\security`：7 passed
  - `python -m pytest server\tests`：67 passed
  - `npm run build`：passed
  - `python web\admin\tests\t09_knowledge_playwright.py; python web\admin\tests\t11_chat_playwright.py; python web\admin\tests\t12_citation_explanation_playwright.py; python web\admin\tests\t13_api_key_playwright.py; python web\admin\tests\t17_release_playwright.py`：passed
  - `python scripts\perf\retrieval_baseline.py 10`：p50 1.268 ms，p95 4.813 ms，failureRate 0.0%
  - `python scripts\perf\chat_first_token_baseline.py 5`：p50 23.988 ms，p95 75.817 ms，failureRate 0.0%
- 环境限制：
  - 本机未安装 Docker CLI，`docker compose -f deploy\docker-compose.yml config` 无法执行，错误为 `docker` 命令不存在。
  - Docker runtime smoke 需在具备 Docker 的机器上按 `release-checklist.md` 复验。

## 完成任务进度

95%
