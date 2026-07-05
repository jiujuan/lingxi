# V1.1 开发 Roadmap：企业级 AI 知识库系统 MVP

## 说明

来源：

- `docs/design/v1.1/v1.1-product-prd.md`
- `docs/design/v1.1/01-technical-architecture.md`
- `docs/design/v1.1/02-database-design-and-sql.md`
- `docs/design/v1.1/03-api-design.md`
- `docs/design/v1.1/04-frontend-ui-interaction-design.md`
- `docs/design/v1.1/05-frontend-backend-interaction-flow.md`
- `docs/design/v1.1/06-coding-and-naming-standards.md`

拆分原则：

- 每个里程碑都是一个可落地、可测试、可独立验收的纵向切片。
- 优先打通主链路，再补管理、观测和上线质量。
- 后一个里程碑可以依赖前一个里程碑，但不反向依赖。
- 明确不做 GraphRAG、IM 深度接入、Widget SDK、客服工单、SaaS 计费后台。

## Roadmap 总览

| 里程碑 | 任务文档 | 目标 | 依赖 |
| --- | --- | --- | --- |
| M01 | `T01-runtime-foundation-todo.md` | 后端、前端、Docker、日志和测试骨架可启动 | 无 |
| M02 | `T02-auth-rbac-todo.md` | 登录、用户、角色、权限与审计上下文 | T01 |
| M03 | `T03-document-schema-permission-todo.md` | 文档、权限规则、QA、Chat、日志核心表和 Repository | T01、T02 |
| M04 | `T04-model-provider-config-todo.md` | 模型供应商、模型实例、连接测试、密钥脱敏 | T02、T03 |
| M05 | `T05-import-job-upload-todo.md` | 文档上传任务、文件绑定、对象存储和任务轮询 API | T03 |
| M06 | `T06-document-parser-worker-todo.md` | 解析 Worker、解析产物、Chunk、失败重试 | T04、T05 |
| M07 | `T07-qa-split-worker-todo.md` | QA 拆分 Worker、QA 对落库、重新生成 | T04、T06 |
| M08 | `T08-embedding-index-todo.md` | QA question 向量化、全文索引、READY 状态 | T04、T07 |
| M09 | `T09-knowledge-ui-todo.md` | 知识库中心 UI：列表、上传、详情、QA、权限 | T05、T08 |
| M10 | `T10-retrieval-engine-todo.md` | SQL 权限过滤、pgvector、tsvector、RRF、轻量 ReRank | T08 |
| M11 | `T11-chat-sse-todo.md` | Web Chat API 和 UI 流式问答、拒答、反馈 | T09、T10 |
| M12 | `T12-citations-explanation-todo.md` | 引用原文、引用快照、检索解释 | T10、T11 |
| M13 | `T13-api-key-management-todo.md` | API Key 创建、禁用、轮换、限流和调用日志 | T02、T03 |
| M14 | `T14-openai-compatible-api-todo.md` | `/v1/chat/completions` 流式/非流式与引用扩展 | T10、T13 |
| M15 | `T15-logs-observability-todo.md` | 任务日志、模型日志、API 日志、审计日志排障页 | T05、T11、T13 |
| M16 | `T16-dashboard-settings-todo.md` | 总览指标、系统设置、检索参数和数据保留 | T09、T15 |
| M17 | `T17-e2e-hardening-release-todo.md` | 端到端验收、安全回归、浏览器验证和交付检查 | T01-T16 |

## 阶段划分

### Phase 1：基础工程与权限底座

- M01：运行时和工程骨架。
- M02：登录、RBAC、审计上下文。
- M03：数据库模型、迁移和 Repository。

验收门槛：

- 后端、前端、PostgreSQL、Redis 可本地启动。
- 登录可用，权限码可返回。
- Alembic migration 可从空库执行。
- 文档权限过滤单元测试通过。

### Phase 2：知识入库闭环

- M04：模型供应商配置。
- M05：上传任务和对象存储。
- M06：文档解析 Worker。
- M07：QA 拆分 Worker。
- M08：Embedding 和索引。
- M09：知识库中心前端。

验收门槛：

- 管理员可上传文档并看到任务状态。
- Worker 可把样本文档处理到 `READY`。
- 文档详情可看到原文片段、QA 对和失败日志。
- 失败任务可重试。

### Phase 3：可信问答闭环

- M10：混合检索和轻量 ReRank。
- M11：Chat SSE 问答。
- M12：引用和检索解释。

验收门槛：

- 员工提问能获得流式回答。
- 有答案回答至少展示 1 条引用。
- 无答案问题明确拒答。
- 无权文档不进入候选、Prompt、回答或引用。

### Phase 4：外部 API 与运维可观测

- M13：API Key 管理。
- M14：OpenAI 兼容 API。
- M15：日志与任务排障。
- M16：Dashboard 和系统设置。

验收门槛：

- API Key 可创建、禁用、轮换。
- 内部系统可调用 `/v1/chat/completions`。
- 日志页可按 request_id、run_id、task_run_id 排障。
- 模型密钥、API Key、Authorization header 不出现在日志中。

### Phase 5：种子客户试点准备

- M17：端到端、安全、浏览器、部署和验收检查。

验收门槛：

- 核心 E2E 链路通过。
- 桌面和移动宽度浏览器验证通过。
- Docker Compose 私有部署可运行。
- PRD 验收清单可映射到测试证据。

## 关键风险与缓解

| 风险 | 影响 | 缓解 |
| --- | --- | --- |
| 文档解析质量不稳定 | QA 对质量差，引用不准 | ParserAdapter 保留解析产物和失败重试；先用样本文档建立测试集 |
| Embedding 维度变更 | 向量列和索引不可复用 | M04 记录维度；M08 检查维度并提示重建 |
| 权限过滤遗漏 | 高危数据泄露 | M03/M10/M17 单独做权限过滤安全测试 |
| SSE 和代理配置不稳 | Chat 首字响应和流式体验差 | M11/M17 在 Nginx/Caddy 下验证 SSE |
| 模型供应商不可用 | 入库和问答失败 | M04 提供 fake provider 和连接测试，业务错误明确可重试 |
| 任务重试重复写数据 | QA 对、Chunk、Embedding 重复 | M06-M08 以内容 hash 和资源 ID 做幂等 |

## 范围外约束

- 不做 GraphRAG、多跳图谱推理。
- 不做企业微信、飞书、钉钉等 IM 深度接入。
- 不做 Widget SDK。
- 不做客服工单系统。
- 不做 SaaS 计费和多租户商业后台。
- 不做独立向量数据库、Elasticsearch/OpenSearch 必选部署。
