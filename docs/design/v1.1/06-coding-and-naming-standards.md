# V1.1 前端与后端代码规范、文件命名规范

版本：V1.1  
日期：2026-07-05  
来源：`docs/design/v1.1/v1.1-product-prd.md`、`docs/design/v1.1/v1.1-technology-selection.md`  
适用范围：`server/`、`web/admin/`

## 1. 总体规范

### 1.1 工程原则

- 业务边界优先于技术分层，模块内聚，跨模块通过 Service 或 API 契约协作。
- API 契约以 OpenAPI Schema 为准，前后端同时更新。
- 管理 API 使用 `/api/v1`，OpenAI 兼容接口使用 `/v1`。
- 数据库字段使用 `snake_case`，API 字段使用 `camelCase`。
- 枚举值使用 `UPPER_SNAKE_CASE`。
- 所有外部输入只在边界校验：API 请求、表单提交、OpenAI 兼容请求、第三方响应、环境变量。
- 第三方 SDK 只能出现在 Adapter 层。
- Secret、Token、API Key、Authorization header 不得写入日志。
- 长任务必须有状态、错误、重试和幂等设计。
- 文档检索必须在 SQL 阶段完成权限过滤，不允许先召回后过滤。
- V1.1 不新增 Widget、IM 深度接入、工单、计费后台相关代码入口。

### 1.2 通用命名

| 类型 | 规范 | 示例 |
| --- | --- | --- |
| 数据库表 | 复数 `snake_case` | `documents`、`qa_pairs`、`query_runs` |
| 数据库列 | `snake_case` | `created_at`、`tenant_id`、`question_embedding` |
| API 路径 | 复数名词，kebab 或普通复数资源名 | `/api/v1/import-jobs` |
| API 字段 | `camelCase` | `createdAt`、`tenantId`、`qaPairCount` |
| 枚举值 | `UPPER_SNAKE_CASE` | `QA_SPLITTING`、`MODEL_UNAVAILABLE` |
| Python 文件 | `snake_case.py` | `model_config.py`、`import_jobs.py` |
| Python 类 | `PascalCase` | `ImportService`、`ParserAdapter` |
| TypeScript 组件 | `PascalCase.tsx` | `DocumentTable.tsx` |
| TypeScript hook | `useXxx.ts` | `useImportJob.ts` |
| 前端 feature 目录 | `kebab-case` | `model-config`、`api-keys` |
| 测试文件 | `test_*.py`、`*.test.tsx` | `test_retrieval.py`、`ChatPage.test.tsx` |

## 2. 后端代码规范

### 2.1 技术栈

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- Celery
- PostgreSQL 16+ + pgvector
- Redis
- pytest + httpx
- structlog + OpenTelemetry

### 2.2 后端目录规范

```text
server/
├── app/
│   ├── main.py
│   ├── api/
│   │   └── v1/
│   ├── openai_compat/
│   ├── core/
│   ├── db/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   ├── repositories/
│   ├── integrations/
│   ├── tasks/
│   └── tests/
```

目录职责：

| 目录 | 职责 |
| --- | --- |
| `api/v1` | FastAPI 管理 API 路由、鉴权依赖、请求响应映射 |
| `openai_compat` | OpenAI 兼容协议、请求映射、流式响应封装 |
| `core` | 配置、安全、错误、权限、日志、ID、限流 |
| `db` | Session、Base、迁移入口 |
| `models` | SQLAlchemy ORM 模型 |
| `schemas` | Pydantic 请求、响应、查询参数 Schema |
| `services` | 业务编排、状态流转、任务投递 |
| `repositories` | 数据库查询和持久化 |
| `integrations` | 模型、解析器、对象存储、中文分词 Adapter |
| `tasks` | Celery 任务入口和队列注册 |
| `tests` | 单元、集成、契约、Worker、安全测试 |

### 2.3 后端依赖规则

允许依赖：

```text
api -> schemas
api -> services
openai_compat -> schemas
openai_compat -> services
services -> repositories
services -> integrations
services -> task dispatch
repositories -> models
repositories -> db
tasks -> services
integrations -> third-party SDKs
```

禁止依赖：

- `repositories` 调用 `services`、`api` 或第三方 SDK。
- `api` 直接访问数据库模型或供应商 SDK。
- `models` 依赖 `schemas`、`services` 或 `api`。
- `services` 返回 FastAPI `Response`、`Request` 或前端专用结构。
- `tasks` 绕过 Service 直接散乱更新业务状态。
- `openai_compat` 复制一套独立业务逻辑；它只能做协议适配。

### 2.4 API 路由命名规范

路由文件按资源命名：

```text
api/v1/auth.py
api/v1/dashboard.py
api/v1/documents.py
api/v1/import_jobs.py
api/v1/qa_pairs.py
api/v1/chat.py
api/v1/retrieval.py
api/v1/model_config.py
api/v1/api_keys.py
api/v1/logs.py
api/v1/users.py
api/v1/settings.py
openai_compat/routes.py
```

路由函数命名：

```python
async def list_documents(...): ...
async def get_document(...): ...
async def update_document(...): ...
async def delete_document(...): ...
async def create_import_job(...): ...
async def retry_import_job(...): ...
async def create_message_run(...): ...
```

REST 路径规则：

- 使用复数资源名：`/documents`、`/import-jobs`、`/api-keys`。
- 不使用动词路径：避免 `/createDocument`、`/getUsers`。
- 复杂动作使用子资源：`/import-jobs/{jobId}/retries`、`/model-providers/{id}/connection-tests`。
- 部分更新使用 `PATCH`。
- 删除默认软删除，返回 `204` 或删除后的状态对象。

### 2.5 Schema 命名规范

Pydantic Schema 按用途拆分：

```text
DocumentCreate
DocumentUpdate
DocumentRead
DocumentListItem
DocumentListParams
DocumentListResponse

ImportJobCreate
ImportJobRead
ImportJobFileCreate
ImportJobRetryRequest

QaPairRead
QaPairListParams
QaRegenerationCreate

ChatSessionCreate
ChatSessionRead
MessageRunCreate
MessageRunRead
CitationRead

ModelProviderCreate
ModelProviderUpdate
ModelProviderRead
ModelConnectionTestRead

ApiKeyCreate
ApiKeyRead
ApiKeyCreateResponse
```

规则：

- 输入和输出分离，不能复用 ORM 模型作为 API 响应。
- 列表响应统一使用分页包装。
- Query 参数单独建 `ListParams`。
- Secret 输入字段只出现在 Create/Update，不出现在 Read。
- 响应字段使用 `camelCase` 序列化。
- OpenAI 兼容 Schema 放在 `openai_compat/schemas.py`，不污染管理 API Schema。

### 2.6 Service 命名规范

Service 以领域能力命名：

```text
AuthService
UserAccessService
DocumentService
ImportService
QaSplitService
RetrievalService
ChatService
ModelConfigService
ApiKeyService
TaskLogService
AuditService
SettingsService
```

方法命名：

```python
create_import_job()
bind_import_job_file()
retry_import_job()
update_document_permissions()
regenerate_qa_pairs()
generate_answer_stream()
build_retrieval_explanation()
test_model_connection()
rotate_api_key()
write_audit_log()
```

规则：

- Service 方法表达业务动作，不暴露数据库细节。
- 状态流转集中在 Service。
- 跨模块写操作必须记录审计日志。
- 需要异步执行的动作只投递任务，不在 API 请求内阻塞。
- 检索 Service 必须接收明确的 `AccessContext`，不能让调用方手写权限 SQL。

### 2.7 Repository 命名规范

Repository 以聚合或表组命名：

```text
UserRepository
DocumentRepository
ImportJobRepository
QaPairRepository
ChatRepository
RetrievalRepository
ModelConfigRepository
ApiKeyRepository
LogRepository
SettingsRepository
```

方法命名：

```python
get_by_id()
list_by_filters()
create()
update()
soft_delete()
exists_by_checksum()
lock_for_update()
list_authorized_qa_pairs()
```

规则：

- Repository 查询方法必须显式接受 `tenant_id`。
- 需要权限过滤的查询必须接受 `AccessContext` 或由专用方法封装。
- 列表查询默认排除 `deleted_at IS NOT NULL`。
- 大列表必须分页，禁止一次性返回全部。
- Repository 不做跨领域状态流转，复杂规则放 Service。

### 2.8 Model 命名规范

SQLAlchemy 模型类使用单数 `PascalCase`：

```text
Tenant -> tenants
Department -> departments
User -> users
Role -> roles
Document -> documents
DocumentAccessRule -> document_access_rules
ImportJob -> import_jobs
DocumentChunk -> document_chunks
QaPair -> qa_pairs
ChatSession -> chat_sessions
ChatMessage -> chat_messages
QueryRun -> query_runs
QueryCitation -> query_citations
ModelProvider -> model_providers
ApiKey -> api_keys
AuditLog -> audit_logs
```

规则：

- ORM 属性使用 `snake_case`，Schema 层转换为 `camelCase`。
- JSONB 字段命名为 `metadata` 时，如与 SQLAlchemy 保留属性冲突，Python 属性可用 `metadata_`，数据库列仍为 `metadata`。
- 外键字段使用 `{resource}_id`。
- 时间字段使用 `timestamptz`。
- 向量字段统一命名为 `{field}_embedding`。
- 全文检索源字段命名为 `search_text`，生成列命名为 `search_vector`。

### 2.9 Adapter 命名规范

目录：

```text
integrations/
├── model_providers/
├── storage/
├── parsers/
└── tokenizers/
```

基类文件统一命名 `base.py`：

```python
class ChatProvider: ...
class EmbeddingProvider: ...
class ParserAdapter: ...
class ObjectStorageAdapter: ...
class TokenizerAdapter: ...
```

实现文件：

```text
model_providers/openai_compatible.py
model_providers/claude.py
model_providers/ollama.py
model_providers/internal_gateway.py
storage/minio.py
storage/local.py
parsers/mineru.py
parsers/lightweight.py
tokenizers/jieba_tokenizer.py
tokenizers/pkuseg_tokenizer.py
```

规则：

- Adapter 内统一处理超时、重试、错误码和日志字段。
- 第三方响应必须校验结构。
- 不允许业务层直接调用供应商 SDK。
- Adapter 错误转换为系统统一错误码。
- Adapter 日志不得包含密钥、Authorization header 或完整用户文档内容。

### 2.10 Celery 任务规范

任务文件按队列或领域命名：

```text
tasks/parse_tasks.py
tasks/qa_tasks.py
tasks/embedding_tasks.py
tasks/maintenance_tasks.py
```

任务命名：

```python
parse_document_task
split_document_qa_task
embed_qa_pairs_task
refresh_document_index_task
aggregate_missed_questions_task
cleanup_expired_logs_task
```

规则：

- 每个任务写入 `task_runs`。
- 任务参数传资源 ID，不传大对象。
- 任务必须幂等，重试不产生重复数据。
- 任务失败记录结构化错误，便于前端展示。
- 不同资源消耗进入不同队列：`parse`、`qa`、`embedding`、`maintenance`。
- Worker 不得绕过 Service 更新文档最终状态。

### 2.11 检索与 RAG 代码规范

推荐模块：

```text
services/retrieval_service.py
services/rerank_service.py
services/prompt_builder.py
repositories/retrieval_repository.py
schemas/retrieval.py
```

规则：

- `RetrievalService` 负责检索编排，不直接调用 FastAPI 对象。
- `RetrievalRepository` 封装带权限过滤的 pgvector 和 tsvector 查询。
- RRF 和轻量 ReRank 必须可单元测试。
- Prompt 构造必须把系统规则、用户问题和参考资料分段隔离。
- 低置信度必须走拒答分支。
- `retrieval_snapshot` 记录可解释信息，但不得保存无权限候选给普通员工可见。

### 2.12 错误与日志规范

统一错误结构：

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求参数不合法",
    "details": {}
  },
  "requestId": "req_..."
}
```

日志字段：

```text
request_id
run_id
task_run_id
tenant_id
actor_id
module
action
resource_type
resource_id
status
latency_ms
error_code
```

规则：

- 业务异常使用明确错误码。
- `500` 不暴露内部堆栈给前端。
- 第三方依赖错误保留供应商、模型、耗时、错误码，不记录 Secret。
- AI 链路额外记录 `run_id`。
- API Key 日志只记录 `key_prefix` 或 `api_key_id`，不记录明文。

### 2.13 后端测试命名

```text
tests/unit/test_access_rules.py
tests/unit/test_rrf_rerank.py
tests/unit/test_prompt_builder.py
tests/unit/test_object_key.py
tests/integration/test_documents_api.py
tests/integration/test_import_jobs_api.py
tests/integration/test_chat_sse.py
tests/integration/test_openai_compat_api.py
tests/contract/test_openapi_schema.py
tests/worker/test_parse_document_task.py
tests/worker/test_qa_split_task.py
tests/worker/test_embedding_task.py
tests/security/test_api_key.py
tests/security/test_document_permission_filter.py
```

测试要求：

- Unit：权限判断、RRF、轻量 ReRank、Prompt 构造、object key 校验、状态机。
- Integration：API + DB、上传任务、权限变更、Chat SSE、OpenAI 兼容接口。
- Contract：OpenAPI Schema、错误响应、分页响应。
- Worker：解析重试、QA 拆分、Embedding 批处理、任务幂等。
- Security：文档权限 SQL 前置过滤、API Key、上传校验、Secret 脱敏。

## 3. 前端代码规范

### 3.1 技术栈

- React
- TypeScript
- Vite
- Ant Design + ProComponents
- TanStack Query
- ECharts
- Vitest
- Playwright

### 3.2 前端目录规范

```text
web/admin/src/
├── app/
├── routes/
├── features/
│   ├── dashboard/
│   ├── knowledge/
│   ├── chat/
│   ├── model-config/
│   ├── api-keys/
│   ├── logs/
│   ├── access-control/
│   └── settings/
├── components/
├── api/
├── auth/
└── styles/
```

目录职责：

| 目录 | 职责 |
| --- | --- |
| `app` | 应用入口、Provider、全局布局 |
| `routes` | 路由定义和权限路由 |
| `features` | 按业务模块组织页面、组件、hooks |
| `components` | 跨业务共享组件 |
| `api` | API client、类型、请求封装、SSE 封装 |
| `auth` | token、登录状态、权限缓存 |
| `styles` | 全局样式、主题变量 |

### 3.3 Feature 目录规范

每个 feature 推荐结构：

```text
features/knowledge/
├── pages/
│   ├── DocumentListPage.tsx
│   ├── DocumentDetailPage.tsx
│   └── ImportPage.tsx
├── components/
│   ├── DocumentTable.tsx
│   ├── DocumentFilters.tsx
│   ├── ImportJobTimeline.tsx
│   ├── QaPairList.tsx
│   └── PermissionEditor.tsx
├── hooks/
│   ├── useDocuments.ts
│   ├── useImportJob.ts
│   └── useQaPairs.ts
├── api/
│   └── knowledgeApi.ts
├── types.ts
└── constants.ts
```

规则：

- 页面组件放 `pages`。
- 仅当前 feature 使用的组件放 feature 内 `components`。
- 跨模块复用组件放全局 `components`。
- API 请求封装放 feature 内 `api` 或全局 `api`，不能在组件中直接 `fetch`。
- 状态、枚举和显示映射放 `constants.ts`。

### 3.4 TypeScript 命名规范

| 类型 | 规范 | 示例 |
| --- | --- | --- |
| 页面组件 | `PascalCasePage.tsx` | `DocumentDetailPage.tsx` |
| 普通组件 | `PascalCase.tsx` | `CitationList.tsx` |
| hook | `useXxx.ts` | `useChatStream.ts` |
| API 文件 | `{resource}Api.ts` | `documentsApi.ts` |
| 类型文件 | `types.ts` | feature 内聚类型 |
| 常量文件 | `constants.ts` | 状态颜色、枚举文案 |
| 工具函数 | `camelCase.ts` | `formatLatency.ts` |
| 测试文件 | `*.test.ts` / `*.test.tsx` | `DocumentTable.test.tsx` |

组件 props：

```ts
type DocumentTableProps = {
  items: DocumentListItem[];
  loading: boolean;
  onOpen: (id: string) => void;
  onRetry: (id: string) => void;
};
```

规则：

- Props 类型与组件同文件，跨组件复用才提到 `types.ts`。
- API DTO 类型优先由 OpenAPI 生成或与 Schema 同步维护。
- 不使用 `any` 绕过 API 类型。
- 事件处理函数以 `handle` 开头：`handleSubmit`、`handleRetry`。

### 3.5 API 调用规范

统一 API client 负责：

- base URL。
- token 注入。
- refresh token。
- API Key 管理页面不暴露真实 Key 到日志。
- `requestId` 读取。
- 统一错误解析。
- JSON 序列化。
- SSE 封装。

组件禁止直接调用 `fetch` 或拼接完整 URL。

TanStack Query key 命名：

```ts
['documents', filters]
['document', documentId]
['qa-pairs', documentId, filters]
['import-job', jobId]
['chat-sessions', filters]
['chat-messages', sessionId]
['query-run', runId]
['model-configs']
['api-keys']
['logs', filters]
```

Mutation 成功后必须失效相关 query：

- 文档创建、编辑、权限变更、删除后失效文档列表和详情。
- 导入任务完成后失效文档列表、文档详情、QA 对列表。
- QA 重新生成后失效 QA 对列表和文档详情。
- SSE 完成后失效会话消息列表和 query run。
- 模型配置保存、测试连接、启停供应商后失效模型配置查询。
- API Key 创建、禁用、轮换后失效 API Key 列表。

### 3.6 UI 组件规范

- 使用 Ant Design 和 ProComponents 的表格、表单、弹窗、上传、分段控件、Tabs。
- 图标优先使用项目已引入的图标库；纯图标按钮需要 tooltip。
- 列表页必须有搜索、筛选、刷新、分页、空状态和错误态。
- 危险操作使用 `danger` 样式和二次确认。
- 表单校验错误展示在字段旁。
- 长任务使用时间线、步骤条或进度条展示阶段。
- 表格操作过多时收敛到“更多”菜单。
- Chat 引用、检索解释、原文片段使用侧栏或抽屉展示，移动端转为全屏抽屉。

### 3.7 前端状态规范

| 状态 | 处理 |
| --- | --- |
| loading | 骨架屏或局部 loading |
| empty | 空状态 + 下一步动作 |
| error | 错误原因 + requestId + 重试 |
| forbidden | 无权限占位 |
| saving | 禁用提交按钮，防重复提交 |
| streaming | AI 回答增量追加，输入框禁用或排队 |
| long-running | 轮询任务状态，页面可离开 |
| secret-created | 明文只展示一次，关闭后不可再查看 |

### 3.8 前端权限规范

- 菜单、按钮、批量操作按权限显示。
- 详情页进入后仍需处理后端 `403`。
- 权限缓存来自登录响应或当前用户接口。
- 用户权限变更后，下一次请求以后端为准。
- 前端不能根据隐藏按钮替代后端校验。

## 4. 数据与状态命名

### 4.1 状态枚举

文档状态：

```text
UPLOADED
PARSING
QA_SPLITTING
EMBEDDING
READY
FAILED
DELETED
```

导入任务状态：

```text
PENDING
RUNNING
COMPLETED
FAILED
CANCELLED
```

导入任务阶段：

```text
CREATED
UPLOADING
PARSING
QA_SPLITTING
EMBEDDING
INDEXING
COMPLETED
FAILED
```

QA 对状态：

```text
ACTIVE
REPLACED
DELETED
EMBEDDING_FAILED
```

Chat 消息角色：

```text
USER
ASSISTANT
SYSTEM
```

Query Run 状态：

```text
RUNNING
COMPLETED
KNOWLEDGE_MISSED
FAILED
```

模型能力：

```text
CHAT
EMBEDDING
QA_SPLIT
```

API Key 状态：

```text
ACTIVE
DISABLED
EXPIRED
```

### 4.2 显示映射

前端需要集中维护枚举显示：

```ts
export const DOCUMENT_STATUS_LABEL: Record<DocumentStatus, string> = {
  UPLOADED: '已上传',
  PARSING: '解析中',
  QA_SPLITTING: 'QA 拆分中',
  EMBEDDING: '向量化中',
  READY: '可问答',
  FAILED: '失败',
  DELETED: '已删除',
};
```

规则：

- 枚举显示文案不能散落在页面组件里。
- 状态颜色映射集中维护。
- 后端新增枚举时，前端必须更新显示映射和测试。

## 5. 安全规范

- Secret 字段只提交给后端，不在前端状态长期保存。
- Token 存储策略需配合安全要求，避免泄露到日志和错误上报。
- Markdown、表格 HTML、解析产物展示必须经过安全清理。
- 文件上传前端先校验类型、大小、数量，后端必须再次校验。
- API Key 只展示前缀、创建时间、最近使用时间，不展示明文。
- 模型 API Key 保存后只展示“已配置”。
- Prompt 模板或系统规则不能被用户输入覆盖。
- 文档原文下载、引用原文查看必须以后端权限校验为准。

## 6. 代码质量与格式

后端推荐：

- Ruff：lint 和 import 排序。
- Black：格式化。
- pytest：测试。
- mypy 或 pyright：关键模块类型检查。

前端推荐：

- ESLint：lint。
- Prettier：格式化。
- TypeScript：类型检查。
- Vitest：单元和组件测试。
- Playwright：关键浏览器流程测试。

提交前至少运行：

```text
后端：pytest
前端：npm run build / npm test / npm run lint，按项目实际脚本执行
```

## 7. 文档同步规范

下列变更必须同步文档：

- 新增或修改 API 端点。
- 新增数据库表、字段、索引或状态枚举。
- 修改文档导入、QA 拆分、Embedding、检索、引用规则。
- 修改 SQL 权限前置过滤逻辑。
- 新增外部 Adapter 或变更 Adapter 契约。
- 修改权限码或角色权限矩阵。
- 修改前端一级导航、页面职责或关键交互。
- 修改 OpenAI 兼容接口扩展字段。

相关文档位置：

```text
docs/design/v1.1/01-technical-architecture.md
docs/design/v1.1/02-database-design-and-sql.md
docs/design/v1.1/03-api-design.md
docs/design/v1.1/04-frontend-ui-interaction-design.md
docs/design/v1.1/05-frontend-backend-interaction-flow.md
docs/design/v1.1/06-coding-and-naming-standards.md
```

## 8. 验收清单

- [ ] 后端模块依赖方向符合 API -> Service -> Repository -> Model。
- [ ] 第三方 SDK 只出现在 Adapter 层。
- [ ] OpenAI 兼容接口只做协议适配，不复制业务逻辑。
- [ ] API、Schema、前端类型、文档同步更新。
- [ ] 所有列表接口分页。
- [ ] 所有写接口做权限校验和审计。
- [ ] 文档检索 SQL 前置权限过滤。
- [ ] 长任务有状态、错误、重试和幂等设计。
- [ ] 前端页面有 loading、empty、error、forbidden 状态。
- [ ] Chat SSE 有开始、增量、引用、完成、错误处理。
- [ ] Secret、Token、API Key 不进入日志。
- [ ] 数据库字段、API 字段、枚举值命名符合规范。
