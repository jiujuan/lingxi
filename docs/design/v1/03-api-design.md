# V1 API 设计文档

版本：V1.0  
日期：2026-07-04  
来源：`docs/design/v1-technical-design.md`  
系统：AI Customer Service Hub

## 1. API 总体规范

### 1.1 基础约定

| 项 | 规范 |
| --- | --- |
| API 前缀 | `/api/v1` |
| API 风格 | REST + SSE |
| 契约来源 | FastAPI OpenAPI Schema |
| 请求格式 | JSON，文件上传可使用 multipart 或预签名上传 |
| 响应字段 | `camelCase` |
| 数据库字段 | `snake_case` |
| 枚举值 | `UPPER_SNAKE_CASE` |
| 时间格式 | ISO 8601，带时区 |
| ID 类型 | UUID 字符串 |
| 列表接口 | 必须分页 |
| 流式回答 | `text/event-stream` |

### 1.2 认证方式

| 场景 | 认证方式 | 说明 |
| --- | --- | --- |
| 后台用户 | Access Token + Refresh Token | 登录后访问管理后台 API |
| 外部系统 | API Key | 用于外部系统调用开放 API |
| 客户侧 Widget | Widget Token | 只允许访问客户侧问答接口 |
| Webhook 回调 | HMAC-SHA256 签名 | 用于服务端事件投递验签 |

后台用户登录使用账号密码，密码后端使用 Argon2id 哈希。Access Token 短有效期，Refresh Token 长有效期并可撤销。

### 1.3 权限模型

后端必须校验权限，前端隐藏按钮不作为安全边界。

关键权限码：

```text
DASHBOARD_READ
KNOWLEDGE_READ
KNOWLEDGE_WRITE
KNOWLEDGE_UPLOAD
KNOWLEDGE_DELETE
FAQ_READ
FAQ_WRITE
FAQ_DELETE
REVIEW_READ
REVIEW_DECIDE
CHAT_READ
CHAT_WRITE
TICKET_READ
TICKET_WRITE
TICKET_COMMENT
ANALYTICS_READ
AI_CONFIG_READ
AI_CONFIG_WRITE
USER_READ
USER_WRITE
ROLE_READ
ROLE_WRITE
SETTING_READ
SETTING_WRITE
INTEGRATION_READ
INTEGRATION_WRITE
WEBHOOK_READ
WEBHOOK_WRITE
```

对象级权限在 Service 或 Repository 层执行。权限不足统一返回 `403 FORBIDDEN`，不泄露对象是否存在。

## 2. 通用请求与响应

### 2.1 分页请求

```http
GET /api/v1/knowledge-items?page=1&pageSize=20&sortBy=updatedAt&sortOrder=desc
```

约束：

- `page` 从 1 开始。
- `pageSize` 默认 20，最大 100。
- `sortBy` 只能使用白名单字段。
- 筛选参数使用 query string，并保持 `camelCase`。

### 2.2 分页响应

```json
{
  "data": [],
  "pagination": {
    "page": 1,
    "pageSize": 20,
    "totalItems": 0,
    "totalPages": 0
  }
}
```

### 2.3 错误响应

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

状态码映射：

| HTTP 状态 | 语义 | 示例错误码 |
| --- | --- | --- |
| 400 | 请求格式错误 | `BAD_REQUEST` |
| 401 | 未认证 | `UNAUTHENTICATED` |
| 403 | 无权限 | `FORBIDDEN` |
| 404 | 资源不存在 | `NOT_FOUND` |
| 409 | 冲突 | `CONFLICT`、`VERSION_CONFLICT` |
| 413 | 上传体过大 | `PAYLOAD_TOO_LARGE` |
| 422 | 业务校验失败 | `VALIDATION_ERROR` |
| 429 | 限流 | `RATE_LIMITED` |
| 500 | 服务端错误 | `INTERNAL_ERROR` |
| 503 | 依赖不可用 | `DEPENDENCY_UNAVAILABLE` |

所有错误响应必须包含 `requestId`。

### 2.4 幂等与并发

- 创建导入任务、Webhook 事件投递、消息生成任务必须有可追踪资源 ID。
- Worker 重试不得产生重复 Chunk、重复引用或重复通知。
- 审核、发布、归档、关闭工单等状态流转接口需要校验当前状态。
- 对需要防止重复提交的写接口，可使用 `Idempotency-Key` 请求头。

## 3. 核心资源模型

### 3.1 通用字段

```json
{
  "id": "uuid",
  "tenantId": "uuid",
  "createdAt": "2026-07-04T00:00:00+08:00",
  "updatedAt": "2026-07-04T00:00:00+08:00",
  "createdBy": "uuid",
  "updatedBy": "uuid"
}
```

### 3.2 KnowledgeItem

```json
{
  "id": "uuid",
  "title": "退款政策说明",
  "type": "PDF",
  "categoryId": "uuid",
  "source": "UPLOAD",
  "status": "PUBLISHED",
  "currentVersionId": "uuid",
  "summary": "知识摘要",
  "tags": [
    { "id": "uuid", "name": "退款", "color": "#1677ff" }
  ],
  "publishedAt": "2026-07-04T00:00:00+08:00",
  "archivedAt": null,
  "updatedAt": "2026-07-04T00:00:00+08:00"
}
```

### 3.3 ImportJob

```json
{
  "id": "uuid",
  "sourceType": "FILE",
  "status": "RUNNING",
  "stage": "EMBEDDING",
  "progress": 70,
  "errorCode": null,
  "errorMessage": null,
  "files": [
    {
      "id": "uuid",
      "fileName": "faq.pdf",
      "mimeType": "application/pdf",
      "fileSize": 1200344,
      "checksum": "sha256:..."
    }
  ]
}
```

### 3.4 MessageRun SSE 事件

`POST /api/v1/conversations/{conversationId}/message-runs` 默认返回 SSE。

事件类型：

```text
run_started
delta
citation
done
error
```

示例：

```text
event: run_started
data: {"runId":"...","messageId":"..."}

event: delta
data: {"text":"根据已发布知识，"}

event: citation
data: {"knowledgeId":"...","chunkId":"...","title":"退款政策","pageNo":3,"rank":1}

event: done
data: {"messageId":"...","latencyMs":1350,"tokenUsage":{"input":1200,"output":320}}
```

客户端不支持 SSE 时可传 `stream=false` 返回普通 JSON。

## 4. 核心端点

### 4.1 认证与用户

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/login` | 登录 | Public |
| POST | `/api/v1/auth/refresh` | 刷新 Token | Authenticated |
| POST | `/api/v1/auth/logout` | 登出 | Authenticated |
| GET | `/api/v1/users` | 用户列表 | `USER_READ` |
| POST | `/api/v1/users` | 创建用户 | `USER_WRITE` |
| PATCH | `/api/v1/users/{userId}` | 更新用户 | `USER_WRITE` |
| GET | `/api/v1/roles` | 角色列表 | `ROLE_READ` |
| PATCH | `/api/v1/roles/{roleId}/permissions` | 更新角色权限 | `ROLE_WRITE` |

登录请求：

```json
{
  "email": "admin@example.com",
  "password": "********"
}
```

登录响应：

```json
{
  "accessToken": "jwt",
  "refreshToken": "opaque-token",
  "expiresIn": 1800,
  "user": {
    "id": "uuid",
    "name": "管理员",
    "email": "admin@example.com",
    "permissions": ["DASHBOARD_READ", "KNOWLEDGE_READ"]
  }
}
```

### 4.2 Dashboard

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/dashboard/summary` | 今日指标 | `DASHBOARD_READ` |
| GET | `/api/v1/dashboard/trends` | 趋势数据 | `DASHBOARD_READ` |
| GET | `/api/v1/dashboard/recent-missed-questions` | 最近未命中 | `DASHBOARD_READ` |
| GET | `/api/v1/dashboard/pending-reviews` | 待审核知识 | `REVIEW_READ` |

查询参数：

- `dateRange=TODAY|LAST_7_DAYS|LAST_30_DAYS|CUSTOM`
- `startDate`
- `endDate`
- `channel`

Dashboard 接口应优先读取聚合表或缓存，避免实时扫描原始日志。

### 4.3 知识中心

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/knowledge-items` | 知识列表 | `KNOWLEDGE_READ` |
| POST | `/api/v1/knowledge-items` | 手工创建知识 | `KNOWLEDGE_WRITE` |
| GET | `/api/v1/knowledge-items/{knowledgeId}` | 知识详情 | `KNOWLEDGE_READ` |
| PATCH | `/api/v1/knowledge-items/{knowledgeId}` | 更新知识元数据 | `KNOWLEDGE_WRITE` |
| DELETE | `/api/v1/knowledge-items/{knowledgeId}` | 删除知识 | `KNOWLEDGE_DELETE` |
| POST | `/api/v1/knowledge-items/{knowledgeId}/versions` | 新建版本 | `KNOWLEDGE_WRITE` |
| GET | `/api/v1/knowledge-items/{knowledgeId}/chunks` | Chunk 列表 | `KNOWLEDGE_READ` |
| PATCH | `/api/v1/chunks/{chunkId}` | 编辑 Chunk | `KNOWLEDGE_WRITE` |

知识列表筛选：

```http
GET /api/v1/knowledge-items?keyword=退款&status=PUBLISHED&type=PDF&categoryId=...&tagId=...&page=1&pageSize=20
```

更新知识元数据：

```json
{
  "title": "退款政策说明",
  "categoryId": "uuid",
  "tagIds": ["uuid"],
  "summary": "更新后的摘要"
}
```

编辑已发布知识时，后端必须创建新版本或让知识重新进入审核流程，不能直接覆盖线上检索内容。

### 4.4 上传任务

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/api/v1/import-jobs` | 创建导入任务 | `KNOWLEDGE_UPLOAD` |
| POST | `/api/v1/import-jobs/{jobId}/files` | 绑定上传文件 | `KNOWLEDGE_UPLOAD` |
| GET | `/api/v1/import-jobs/{jobId}` | 查询任务状态 | `KNOWLEDGE_UPLOAD` |
| POST | `/api/v1/import-jobs/{jobId}/retries` | 重试任务 | `KNOWLEDGE_UPLOAD` |
| DELETE | `/api/v1/import-jobs/{jobId}` | 删除失败任务 | `KNOWLEDGE_UPLOAD` |

创建导入任务：

```json
{
  "sourceType": "FILE",
  "parseOptions": {
    "preferredParser": "MINERU",
    "enableOcr": true,
    "enableTableStructure": true,
    "enableFormula": false,
    "fallbackEnabled": true
  }
}
```

状态阶段：

```text
CREATED
UPLOADING
PARSING
CHUNKING
EMBEDDING
PENDING_REVIEW
COMPLETED
FAILED
```

失败时必须返回 `errorCode`、`errorMessage` 和可重试标记。

### 4.5 FAQ 与审核

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/faqs` | FAQ 列表 | `FAQ_READ` |
| POST | `/api/v1/faqs` | 新建 FAQ | `FAQ_WRITE` |
| PATCH | `/api/v1/faqs/{faqId}` | 更新 FAQ | `FAQ_WRITE` |
| DELETE | `/api/v1/faqs/{faqId}` | 删除 FAQ | `FAQ_DELETE` |
| GET | `/api/v1/review-tasks` | 审核列表 | `REVIEW_READ` |
| PATCH | `/api/v1/review-tasks/{taskId}` | 审核通过/驳回 | `REVIEW_DECIDE` |

审核请求：

```json
{
  "decision": "APPROVED",
  "reason": "内容准确，允许发布"
}
```

驳回时 `reason` 必填。审核通过后的状态取决于 `review_policies.autoPublish` 和审核人角色。

### 4.6 AI 客服

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/conversations` | 会话列表 | `CHAT_READ` |
| POST | `/api/v1/conversations` | 创建会话 | `CHAT_WRITE` |
| GET | `/api/v1/conversations/{conversationId}/messages` | 消息列表 | `CHAT_READ` |
| POST | `/api/v1/conversations/{conversationId}/message-runs` | 创建并流式生成回答 | `CHAT_WRITE` |
| POST | `/api/v1/messages/{messageId}/feedback` | 点赞/点踩 | `CHAT_WRITE` |
| POST | `/api/v1/conversations/{conversationId}/ticket-links` | 会话转工单 | `TICKET_WRITE` |

创建回答请求：

```json
{
  "question": "退货退款周期是多久？",
  "stream": true,
  "retrieverConfigId": "uuid"
}
```

规则：

- 有可信知识时，优先基于检索结果回答。
- 检索无结果或低于阈值时，返回知识不足回答并记录 `missed_questions`。
- 回答必须带引用，闲聊和知识不足回答除外。
- 高风险分类低置信度时建议转人工。
- 多轮对话不得跨客户泄露上下文。

### 4.7 工单

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/tickets` | 工单列表 | `TICKET_READ` |
| POST | `/api/v1/tickets` | 创建工单 | `TICKET_WRITE` |
| GET | `/api/v1/tickets/{ticketId}` | 工单详情 | `TICKET_READ` |
| PATCH | `/api/v1/tickets/{ticketId}` | 更新状态/负责人/优先级 | `TICKET_WRITE` |
| POST | `/api/v1/tickets/{ticketId}/comments` | 添加备注 | `TICKET_COMMENT` |
| GET | `/api/v1/tickets/{ticketId}/events` | 状态流转记录 | `TICKET_READ` |

工单状态：

```text
OPEN -> IN_PROGRESS -> RESOLVED -> CLOSED
OPEN -> CANCELLED
IN_PROGRESS -> OPEN
RESOLVED -> IN_PROGRESS
```

关闭工单必须提交处理结果。工单关闭后可选择沉淀为 FAQ 草稿。

### 4.8 知识运营

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/analytics/ai-hit-rate` | 命中率分析 | `ANALYTICS_READ` |
| GET | `/api/v1/analytics/missed-questions` | 未命中列表 | `ANALYTICS_READ` |
| POST | `/api/v1/analytics/missed-questions/{id}/faq-drafts` | 生成 FAQ 草稿 | `FAQ_WRITE` |
| GET | `/api/v1/analytics/top-knowledge` | 热门知识 | `ANALYTICS_READ` |
| GET | `/api/v1/analytics/top-questions` | 热门问题 | `ANALYTICS_READ` |
| GET | `/api/v1/analytics/knowledge-health` | 知识健康 | `ANALYTICS_READ` |

生成 FAQ 草稿后必须进入审核流程，不能自动发布。

### 4.9 AI 配置、系统设置与集成

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/ai/model-providers` | 模型供应商列表 | `AI_CONFIG_READ` |
| POST | `/api/v1/ai/model-providers` | 新增供应商 | `AI_CONFIG_WRITE` |
| POST | `/api/v1/ai/model-providers/{id}/connection-tests` | 测试连接 | `AI_CONFIG_WRITE` |
| GET | `/api/v1/ai/prompt-templates` | Prompt 模板 | `AI_CONFIG_READ` |
| POST | `/api/v1/ai/prompt-templates` | 创建模板 | `AI_CONFIG_WRITE` |
| GET | `/api/v1/ai/retriever-configs` | RAG 参数 | `AI_CONFIG_READ` |
| PATCH | `/api/v1/ai/retriever-configs/{id}` | 更新 RAG 参数 | `AI_CONFIG_WRITE` |
| GET | `/api/v1/settings` | 系统设置 | `SETTING_READ` |
| PATCH | `/api/v1/settings` | 更新系统设置 | `SETTING_WRITE` |
| GET | `/api/v1/integrations/channels` | 渠道配置 | `INTEGRATION_READ` |
| PATCH | `/api/v1/integrations/channels/{channelId}` | 配置企业微信/飞书/钉钉 | `INTEGRATION_WRITE` |
| GET | `/api/v1/webhooks` | Webhook 列表 | `WEBHOOK_READ` |
| POST | `/api/v1/webhooks` | 创建 Webhook | `WEBHOOK_WRITE` |

Secret 字段保存后不再明文返回，只返回是否已配置、更新时间和操作者。

### 4.10 Widget API

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/widget/config` | 获取 Widget 配置 | Widget Token |
| POST | `/api/v1/widget/conversations` | 创建客户会话 | Widget Token |
| POST | `/api/v1/widget/conversations/{id}/message-runs` | 客户提问流式回答 | Widget Token |
| POST | `/api/v1/widget/messages/{id}/feedback` | 客户反馈 | Widget Token |

Widget 安全要求：

- 使用单独 Widget Token，不使用后台用户 Token。
- 配置嵌入域名白名单。
- 独立限流，默认每 IP 每分钟 30 次。
- 不向访客暴露内部知识详情页，只展示引用标题和公开摘要。

## 5. Webhook 设计

### 5.1 事件类型

```text
knowledge.published
knowledge.archived
ai.answer.generated
ai.missed_question.detected
ticket.created
ticket.updated
ticket.closed
```

### 5.2 签名

Webhook 使用 HMAC-SHA256。

请求头：

```http
X-Lingxi-Event: ticket.created
X-Lingxi-Delivery: uuid
X-Lingxi-Timestamp: 1783094400
X-Lingxi-Signature: sha256=...
```

签名字符串：

```text
{timestamp}.{raw_body}
```

### 5.3 投递策略

- 每个事件 ID 全局唯一。
- 每次投递写入 `webhook_deliveries`。
- 失败后指数退避，最多 5 次。
- `2xx` 视为成功，其他状态视为失败。
- 超时、DNS、连接失败均记录错误摘要，不记录敏感 Secret。

## 6. 内部 Adapter 接口

业务层不直接调用供应商 SDK，统一通过内部接口。

### 6.1 模型供应商

```python
class ChatProvider:
    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatDelta]:
        ...

    async def complete_chat(self, request: ChatRequest) -> ChatResponse:
        ...

class EmbeddingProvider:
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...

class RerankProvider:
    async def rerank(self, query: str, documents: list[RerankDocument]) -> list[RerankScore]:
        ...
```

### 6.2 文档解析

```python
class ParserAdapter:
    name: str
    version: str

    def supports(self, source: ParseSource) -> bool:
        ...

    async def parse(self, request: ParseRequest) -> ParsedDocument:
        ...
```

解析器必须输出统一 `ParsedDocument`，并校验第三方解析结果。

### 6.3 对象存储

```python
class ObjectStorageAdapter:
    name: str

    async def put_object(self, request: PutObjectRequest) -> StoredObject:
        ...

    async def get_object(self, object_key: str) -> ObjectStream:
        ...

    async def stat_object(self, object_key: str) -> ObjectMetadata:
        ...

    async def delete_object(self, object_key: str) -> None:
        ...

    async def create_presigned_upload(self, request: PresignedUploadRequest) -> PresignedUpload:
        ...

    async def create_presigned_download(self, object_key: str, expires_seconds: int) -> PresignedDownload:
        ...
```

`object_key` 必须相对化，不允许绝对路径、盘符、`..` 和路径穿越。

## 7. API 兼容性规则

- 新增字段必须向后兼容，优先新增可选字段。
- 不删除既有响应字段，不改变字段类型，不复用已废弃枚举含义。
- 列表接口新增筛选条件不能改变默认排序和默认范围。
- 错误响应结构不能按端点变化。
- OpenAPI Schema、前端类型、API 文档必须随接口变更一起提交。
- 外部输入只在边界层校验，内部代码依赖类型契约。

## 8. API 验收清单

- [ ] 每个端点都有输入、输出和错误结构。
- [ ] 所有列表端点支持分页。
- [ ] 所有写端点有权限校验和审计日志。
- [ ] AI 流式端点支持 `run_started`、`delta`、`citation`、`done`、`error`。
- [ ] 上传、解析、Embedding、通知任务失败可查询、可重试。
- [ ] Widget API 不暴露后台用户能力和内部知识详情。
- [ ] Webhook 签名、重试和投递日志可验证。
- [ ] OpenAPI Schema 可作为前端和测试的契约来源。
