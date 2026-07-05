# V1 前端与后端代码规范、文件命名规范

版本：V1.0  
日期：2026-07-04  
来源：`docs/design/v1-technical-design.md`  
适用范围：`server/`、`web/admin/`、`web/widget/`

## 1. 总体规范

### 1.1 工程原则

- 业务边界优先于技术分层，模块内聚，跨模块通过 Service 或 API 契约协作。
- API 契约以 OpenAPI Schema 为准，前后端同时更新。
- 数据库字段使用 `snake_case`，API 字段使用 `camelCase`。
- 枚举值使用 `UPPER_SNAKE_CASE`。
- 所有外部输入只在边界校验：API 请求、表单提交、Webhook、第三方响应、环境变量。
- 第三方 SDK 只能出现在 Adapter 层。
- Secret、Token、API Key、Authorization header 不得写入日志。
- 长任务必须有状态、错误、重试和幂等设计。

### 1.2 通用命名

| 类型 | 规范 | 示例 |
| --- | --- | --- |
| 数据库表 | 复数 `snake_case` | `knowledge_items`、`message_runs` |
| 数据库列 | `snake_case` | `created_at`、`tenant_id` |
| API 路径 | 复数名词，kebab 或普通复数资源名 | `/api/v1/knowledge-items` |
| API 字段 | `camelCase` | `createdAt`、`tenantId` |
| 枚举值 | `UPPER_SNAKE_CASE` | `PENDING_REVIEW`、`IN_PROGRESS` |
| Python 文件 | `snake_case.py` | `ai_config.py`、`model_provider.py` |
| Python 类 | `PascalCase` | `KnowledgeService`、`ParserAdapter` |
| TypeScript 组件 | `PascalCase.tsx` | `KnowledgeTable.tsx` |
| TypeScript hook | `useXxx.ts` | `useKnowledgeItems.ts` |
| 前端 feature 目录 | `kebab-case` | `ai-config`、`access-control` |

## 2. 后端代码规范

### 2.1 技术栈

- Python 3.12+
- FastAPI
- Pydantic v2
- SQLAlchemy 2
- Alembic
- Celery
- pytest + httpx
- structlog + OpenTelemetry

### 2.2 后端目录规范

```text
server/
├── app/
│   ├── main.py
│   ├── api/
│   │   └── v1/
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
| `api/v1` | FastAPI 路由、鉴权依赖、请求响应映射 |
| `core` | 配置、安全、错误、权限、日志、ID、限流 |
| `db` | Session、Base、迁移入口 |
| `models` | SQLAlchemy ORM 模型 |
| `schemas` | Pydantic 请求、响应、查询参数 Schema |
| `services` | 业务编排、状态流转、任务投递 |
| `repositories` | 数据库查询和持久化 |
| `integrations` | 模型、解析器、对象存储、渠道、Webhook Adapter |
| `tasks` | Celery 任务入口和队列注册 |
| `tests` | 单元、集成、契约、Worker、安全测试 |

### 2.3 后端依赖规则

允许依赖：

```text
api -> schemas
api -> services
services -> repositories
services -> integrations
services -> tasks dispatch
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

### 2.4 API 路由规范

路由文件按资源命名：

```text
api/v1/auth.py
api/v1/dashboard.py
api/v1/knowledge.py
api/v1/imports.py
api/v1/faqs.py
api/v1/reviews.py
api/v1/conversations.py
api/v1/tickets.py
api/v1/analytics.py
api/v1/ai_config.py
api/v1/users.py
api/v1/settings.py
api/v1/integrations.py
api/v1/webhooks.py
```

路由函数命名：

```python
async def list_knowledge_items(...): ...
async def create_knowledge_item(...): ...
async def get_knowledge_item(...): ...
async def update_knowledge_item(...): ...
async def delete_knowledge_item(...): ...
```

REST 路径规则：

- 使用复数资源名：`/knowledge-items`、`/tickets`。
- 不使用动词路径：避免 `/createTicket`、`/getUsers`。
- 复杂动作使用子资源：`/model-providers/{id}/connection-tests`、`/import-jobs/{jobId}/retries`。
- 部分更新使用 `PATCH`。
- 删除默认软删除，返回 `204` 或删除后的状态对象。

### 2.5 Schema 命名规范

Pydantic Schema 按用途拆分：

```text
KnowledgeItemCreate
KnowledgeItemUpdate
KnowledgeItemRead
KnowledgeItemListItem
KnowledgeItemListParams
KnowledgeItemListResponse

ImportJobCreate
ImportJobRead
ImportJobFileCreate

TicketCreate
TicketUpdate
TicketRead
TicketListParams
```

规则：

- 输入和输出分离，不能复用 ORM 模型作为 API 响应。
- 列表响应统一使用分页包装。
- Query 参数单独建 `ListParams`。
- Secret 输入字段只出现在 Create/Update，不出现在 Read。
- 响应字段使用 `camelCase` 序列化。

### 2.6 Service 命名规范

Service 以领域能力命名：

```text
KnowledgeService
ImportService
ReviewService
ChatService
RetrievalService
TicketService
AnalyticsService
ConfigService
UserAccessService
IntegrationService
```

方法命名：

```python
create_import_job()
bind_import_job_file()
retry_import_job()
submit_review_decision()
generate_answer_stream()
create_ticket_from_conversation()
generate_faq_draft_from_missed_question()
```

规则：

- Service 方法表达业务动作，不暴露数据库细节。
- 状态流转集中在 Service。
- 跨模块写操作必须记录审计日志。
- 需要异步执行的动作只投递任务，不在 API 请求内阻塞。

### 2.7 Repository 命名规范

Repository 以聚合或表组命名：

```text
KnowledgeRepository
ImportJobRepository
ReviewRepository
ConversationRepository
TicketRepository
AnalyticsRepository
ConfigRepository
UserRepository
```

方法命名：

```python
get_by_id()
list_by_filters()
create()
update()
soft_delete()
exists_by_hash()
lock_for_update()
```

规则：

- Repository 不做权限判断以外的业务状态流转，复杂规则放 Service。
- 查询方法必须显式接受 `tenant_id`。
- 列表查询默认排除 `deleted_at IS NOT NULL`。
- 大列表必须分页，禁止一次性返回全部。

### 2.8 Model 命名规范

SQLAlchemy 模型类使用单数 `PascalCase`：

```text
Tenant -> tenants
KnowledgeItem -> knowledge_items
KnowledgeVersion -> knowledge_versions
ImportJob -> import_jobs
MessageRun -> message_runs
RetrieverConfig -> retriever_configs
```

规则：

- ORM 属性使用 `snake_case`，Schema 层转换为 `camelCase`。
- JSONB 字段命名为 `metadata` 时，如果与 SQLAlchemy 保留属性冲突，Python 属性可用 `metadata_`，数据库列仍为 `metadata`。
- 外键字段使用 `{resource}_id`。
- 时间字段使用 `timestamptz`。

### 2.9 Adapter 命名规范

目录：

```text
integrations/
├── model_providers/
├── channel_providers/
├── storage/
└── parsers/
```

基类文件统一命名 `base.py`：

```python
class ChatProvider: ...
class EmbeddingProvider: ...
class RerankProvider: ...
class ParserAdapter: ...
class ObjectStorageAdapter: ...
class ChannelProvider: ...
```

实现文件：

```text
model_providers/openai.py
model_providers/qwen.py
model_providers/ollama.py
storage/minio.py
storage/local.py
parsers/mineru.py
parsers/lightweight.py
```

规则：

- Adapter 内统一处理超时、重试、错误码和日志字段。
- 第三方响应必须校验结构。
- 不允许业务层直接调用供应商 SDK。
- Adapter 错误转换为系统统一错误码。

### 2.10 Celery 任务规范

任务文件按队列或领域命名：

```text
tasks/import_tasks.py
tasks/embedding_tasks.py
tasks/ai_tasks.py
tasks/analytics_tasks.py
tasks/notification_tasks.py
```

任务命名：

```python
parse_document_task
embed_chunks_task
refresh_knowledge_index_task
generate_faq_draft_task
dispatch_webhook_task
aggregate_dashboard_metrics_task
```

规则：

- 每个任务写入 `task_runs`。
- 任务参数传资源 ID，不传大对象。
- 任务必须幂等，重试不产生重复数据。
- 任务失败记录结构化错误，便于前端展示。
- 不同资源消耗进入不同队列：`parse`、`embedding`、`ai`、`analytics`、`notification`。

### 2.11 错误与日志规范

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

### 2.12 后端测试命名

```text
tests/unit/test_chunking.py
tests/unit/test_permissions.py
tests/integration/test_import_jobs_api.py
tests/integration/test_review_publish_flow.py
tests/contract/test_openapi_schema.py
tests/worker/test_parse_document_task.py
tests/security/test_widget_token.py
```

测试要求：

- Unit：Chunk 切分、权限判断、状态机、RAG 合并排序、Webhook 签名、object key 校验。
- Integration：API + DB、上传任务、审核发布、工单流转、模型适配器模拟、本地路径存储。
- Contract：OpenAPI Schema、错误响应、分页响应。
- Worker：MinerU 解析、轻量 fallback、解析重试、Embedding 批处理、任务幂等。
- Security：RBAC、对象级权限、API Key、Widget Token、上传校验。

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
│   ├── tickets/
│   ├── analytics/
│   ├── ai-config/
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
| `api` | API client、类型、请求封装 |
| `auth` | token、登录状态、权限缓存 |
| `styles` | 全局样式、主题变量 |

Widget 目录：

```text
web/widget/src/
├── widget-entry.tsx
├── chat-widget.tsx
├── api.ts
└── styles.css
```

Widget 不依赖 Admin Web 的路由、布局和全局样式。

### 3.3 Feature 目录规范

每个 feature 推荐结构：

```text
features/knowledge/
├── pages/
│   ├── KnowledgeListPage.tsx
│   ├── KnowledgeDetailPage.tsx
│   ├── ImportCenterPage.tsx
│   ├── FaqPage.tsx
│   └── ReviewPage.tsx
├── components/
│   ├── KnowledgeTable.tsx
│   ├── KnowledgeFilters.tsx
│   ├── ImportJobTimeline.tsx
│   └── CitationList.tsx
├── hooks/
│   ├── useKnowledgeItems.ts
│   └── useImportJob.ts
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
| 页面组件 | `PascalCasePage.tsx` | `TicketDetailPage.tsx` |
| 普通组件 | `PascalCase.tsx` | `CitationList.tsx` |
| hook | `useXxx.ts` | `useConversationMessages.ts` |
| API 文件 | `{resource}Api.ts` | `ticketsApi.ts` |
| 类型文件 | `types.ts` | feature 内聚类型 |
| 常量文件 | `constants.ts` | 状态颜色、枚举文案 |
| 工具函数 | `camelCase.ts` | `formatLatency.ts` |
| 测试文件 | `*.test.ts` / `*.test.tsx` | `KnowledgeTable.test.tsx` |

组件 props：

```ts
type KnowledgeTableProps = {
  items: KnowledgeItemListItem[];
  loading: boolean;
  onEdit: (id: string) => void;
};
```

规则：

- Props 类型与组件同文件，跨组件复用才提到 `types.ts`。
- API DTO 类型优先由 OpenAPI 生成或与 Schema 同步维护。
- 不使用 `any` 绕过 API 类型。
- 事件处理函数以 `handle` 开头：`handleSubmit`、`handleRetry`。

### 3.5 API 调用规范

统一 API client 负责：

- base URL
- token 注入
- refresh token
- `requestId` 读取
- 统一错误解析
- JSON 序列化
- SSE 封装

组件禁止直接调用 `fetch` 或拼接完整 URL。

TanStack Query key 命名：

```ts
['knowledge-items', filters]
['knowledge-item', knowledgeId]
['import-job', jobId]
['conversation-messages', conversationId]
['ticket', ticketId]
['dashboard-summary', dateRange]
```

Mutation 成功后必须失效相关 query：

- 知识创建、编辑、审核、发布、归档、删除后失效知识列表和详情。
- 导入任务完成后失效知识列表和审核列表。
- SSE 完成后失效会话消息列表。
- 工单创建、转派、关闭后失效工单列表和详情。
- 配置保存后失效配置查询。

### 3.6 UI 组件规范

- 使用 Ant Design 和 ProComponents 的表格、表单、弹窗、上传、分段控件、Tabs。
- 图标优先使用项目已引入的图标库；按钮图标需要 tooltip 或明确文字。
- 列表页必须有搜索、筛选、刷新、分页、空状态和错误态。
- 危险操作使用 `danger` 样式和二次确认。
- 表单校验错误展示在字段旁。
- 长任务使用时间线、步骤条或进度条展示阶段。
- 表格操作过多时收敛到“更多”菜单。

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

### 3.8 前端权限规范

- 菜单、按钮、批量操作按权限显示。
- 详情页进入后仍需处理后端 `403`。
- 权限缓存来自登录响应或当前用户接口。
- 用户权限变更后，下一次请求以后端为准。
- 前端不能根据隐藏按钮替代后端校验。

### 3.9 Widget 代码规范

Widget 约束：

- 独立构建，入口为 `widget-entry.tsx`。
- 使用 Web Component 封装样式和生命周期。
- 不依赖 Admin Web 的全局 CSS、路由、权限模块。
- API 只访问 `/api/v1/widget/*`。
- 引用只展示公开标题和摘要，不跳后台详情页。
- 需要处理宿主页面字体、z-index、移动端宽度和 CORS。

Widget 文件命名：

```text
widget-entry.tsx
chat-widget.tsx
api.ts
styles.css
```

## 4. 数据与状态命名

### 4.1 状态枚举

知识状态：

```text
UPLOADING
PARSING
EMBEDDING
PENDING_REVIEW
PUBLISHED
ARCHIVED
FAILED
```

Chunk 状态：

```text
DRAFT
ACTIVE
REINDEX_REQUIRED
ARCHIVED
```

工单状态：

```text
OPEN
IN_PROGRESS
RESOLVED
CLOSED
CANCELLED
```

工单优先级：

```text
LOW
MEDIUM
HIGH
URGENT
```

### 4.2 显示映射

前端需要集中维护枚举显示：

```ts
export const TICKET_STATUS_LABEL: Record<TicketStatus, string> = {
  OPEN: '待处理',
  IN_PROGRESS: '处理中',
  RESOLVED: '已解决',
  CLOSED: '已关闭',
  CANCELLED: '已取消',
};
```

规则：

- 枚举显示文案不能散落在页面组件里。
- 状态颜色映射集中维护。
- 后端新增枚举时，前端必须更新显示映射和测试。

## 5. 安全规范

- Secret 字段只提交给后端，不在前端状态长期保存。
- Token 存储策略需配合安全要求，避免泄露到日志和错误上报。
- Markdown 和富文本展示必须经过后端或前端安全清理。
- 文件上传前端先校验类型、大小、数量，后端必须再次校验。
- Widget 必须校验域名白名单和 Widget Token。
- Prompt 模板编辑不得把用户输入拼接到系统指令之外。
- API Key 只展示前缀和创建时间，不展示明文。

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
- 修改 AI 回答、引用、审核、工单状态流转。
- 新增外部 Adapter 或变更 Adapter 契约。
- 修改权限码或角色权限矩阵。
- 修改前端一级导航、页面职责或关键交互。

相关文档位置：

```text
docs/design/v1/01-technical-architecture.md
docs/design/v1/02-database-design-and-sql.md
docs/design/v1/03-api-design.md
docs/design/v1/04-frontend-ui-interaction-design.md
docs/design/v1/05-frontend-backend-interaction-flow.md
docs/design/v1/06-coding-and-naming-standards.md
```

## 8. 验收清单

- [ ] 后端模块依赖方向符合 API -> Service -> Repository -> Model。
- [ ] 第三方 SDK 只出现在 Adapter 层。
- [ ] API、Schema、前端类型、文档同步更新。
- [ ] 所有列表接口分页。
- [ ] 所有写接口做权限校验和审计。
- [ ] 长任务有状态、错误、重试和幂等设计。
- [ ] 前端页面有 loading、empty、error、forbidden 状态。
- [ ] Widget 与 Admin Web 样式和权限隔离。
- [ ] 数据库字段、API 字段、枚举值命名符合规范。
