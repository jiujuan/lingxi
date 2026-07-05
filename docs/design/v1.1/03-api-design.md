# V1.1 API 设计文档

版本：V1.1  
日期：2026-07-05  
来源：`docs/design/v1.1/v1.1-product-prd.md`、`docs/design/v1.1/v1.1-technology-selection.md`  
系统：企业级 AI 知识库系统（MVP）

## 1. API 总体规范

### 1.1 基础约定

| 项 | 规范 |
| --- | --- |
| 管理 API 前缀 | `/api/v1` |
| OpenAI 兼容 API 前缀 | `/v1` |
| API 风格 | REST + SSE |
| 契约来源 | FastAPI OpenAPI Schema |
| 请求格式 | JSON，文件上传使用 multipart 或预签名上传 |
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
| Web UI 后台用户 | Access Token + Refresh Token | 登录后访问管理 API |
| Web Chat 员工 | Access Token + Refresh Token | 与后台账号体系一致，按用户权限检索 |
| 内部系统调用 | API Key | 调用 OpenAI 兼容接口 |
| Worker 内部调用 | 内部任务上下文 | 不暴露给外部，按资源 ID 和租户上下文执行 |

后台用户登录使用账号密码，密码后端使用 Argon2id 或同等级哈希。Access Token 短有效期，Refresh Token 长有效期并可撤销。

API Key 只保存 hash 和 key 前缀，创建后明文只展示一次。禁用、轮换或过期后立即不可用。

### 1.3 权限模型

后端必须校验权限，前端隐藏按钮不作为安全边界。

关键权限码：

```text
DASHBOARD_READ
DOCUMENT_READ
DOCUMENT_UPLOAD
DOCUMENT_WRITE
DOCUMENT_DELETE
DOCUMENT_PERMISSION_WRITE
QA_PAIR_READ
QA_PAIR_REGENERATE
CHAT_READ
CHAT_WRITE
RETRIEVAL_EXPLAIN_READ
MODEL_CONFIG_READ
MODEL_CONFIG_WRITE
API_KEY_READ
API_KEY_WRITE
LOG_READ
TASK_RETRY
USER_READ
USER_WRITE
ROLE_READ
ROLE_WRITE
SETTING_READ
SETTING_WRITE
AUDIT_READ
```

对象级权限在 Service 或 Repository 查询中执行。文档检索必须在 SQL 阶段基于 `document_access_rules` 前置过滤。权限不足统一返回 `403 FORBIDDEN`，不得泄露无权文档是否存在。

## 2. 通用请求与响应

### 2.1 分页请求

```http
GET /api/v1/documents?page=1&pageSize=20&sortBy=updatedAt&sortOrder=desc
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
  "requestId": "req_20260705_001"
}
```

状态码映射：

| HTTP 状态 | 语义 | 示例错误码 |
| --- | --- | --- |
| 400 | 请求格式错误 | `BAD_REQUEST` |
| 401 | 未认证 | `UNAUTHENTICATED`、`INVALID_API_KEY` |
| 403 | 无权限 | `FORBIDDEN` |
| 404 | 资源不存在 | `NOT_FOUND` |
| 409 | 状态冲突 | `STATE_CONFLICT`、`DUPLICATE_DOCUMENT` |
| 413 | 上传体过大 | `PAYLOAD_TOO_LARGE` |
| 415 | 不支持的媒体类型 | `UNSUPPORTED_FILE_TYPE` |
| 422 | 业务校验失败 | `VALIDATION_ERROR` |
| 429 | 限流 | `RATE_LIMITED` |
| 500 | 服务端错误 | `INTERNAL_ERROR` |
| 503 | 依赖不可用 | `MODEL_UNAVAILABLE`、`PARSER_UNAVAILABLE` |

所有错误响应必须包含 `requestId`。`500` 不返回内部堆栈。

### 2.4 幂等与并发

- 创建上传任务、绑定文件、重试任务、Chat 生成可接受 `Idempotency-Key` 请求头。
- Worker 重试不得产生重复 Chunk、QA 对、Embedding 或引用。
- 文档权限、模型默认配置、API Key 轮换等写操作必须写入审计日志。
- 多次快速提交 Chat 时，后端按会话或用户限流，前端展示排队或防重复提交。

## 3. 核心资源模型

### 3.1 Document

```json
{
  "id": "uuid",
  "title": "退款流程 SOP V3",
  "fileName": "refund-sop-v3.pdf",
  "fileType": "PDF",
  "mimeType": "application/pdf",
  "fileSize": 1200344,
  "status": "READY",
  "parserName": "MINERU",
  "pageCount": 36,
  "qaPairCount": 128,
  "chunkCount": 96,
  "permissions": {
    "departments": [{ "id": "uuid", "name": "客服部" }],
    "roles": [{ "id": "uuid", "name": "知识管理员" }]
  },
  "lastErrorCode": null,
  "lastErrorMessage": null,
  "createdAt": "2026-07-05T00:00:00+08:00",
  "updatedAt": "2026-07-05T00:00:00+08:00"
}
```

### 3.2 ImportJob

```json
{
  "id": "uuid",
  "documentId": "uuid",
  "status": "RUNNING",
  "stage": "QA_SPLITTING",
  "progress": 55,
  "retryCount": 0,
  "errorCode": null,
  "errorMessage": null,
  "createdAt": "2026-07-05T00:00:00+08:00"
}
```

### 3.3 QaPair

```json
{
  "id": "uuid",
  "documentId": "uuid",
  "chunkId": "uuid",
  "question": "已开票订单如何退款？",
  "answer": "已开票订单需先完成发票红冲，再由财务审核后退款。",
  "quote": "已开具发票的订单必须先完成红冲流程...",
  "pageNo": 4,
  "embeddingStatus": "READY",
  "status": "ACTIVE",
  "updatedAt": "2026-07-05T00:00:00+08:00"
}
```

### 3.4 Chat SSE 事件

`POST /api/v1/chat/sessions/{sessionId}/message-runs` 默认返回 SSE。

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
data: {"runId":"run_20260705_001","messageId":"uuid","requestId":"req_..."}

event: delta
data: {"text":"根据已入库文档，"}

event: citation
data: {"citationId":"uuid","documentId":"uuid","qaPairId":"uuid","title":"退款流程 SOP V3","pageNo":4,"rank":1,"score":0.92}

event: done
data: {"messageId":"uuid","latencyMs":1350,"tokenUsage":{"input":1200,"output":320}}
```

客户端不支持 SSE 时可传 `stream=false` 返回普通 JSON。

## 4. 管理 API 端点

### 4.1 认证与用户权限

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/api/v1/auth/login` | 登录 | Public |
| POST | `/api/v1/auth/refresh` | 刷新 Token | Authenticated |
| POST | `/api/v1/auth/logout` | 登出 | Authenticated |
| GET | `/api/v1/auth/me` | 当前用户、部门、角色、权限 | Authenticated |
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
    "departmentId": "uuid",
    "roles": ["SYSTEM_ADMIN"],
    "permissions": ["DASHBOARD_READ", "DOCUMENT_READ"]
  }
}
```

### 4.2 总览 Dashboard

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/dashboard/summary` | MVP 核心指标 | `DASHBOARD_READ` |
| GET | `/api/v1/dashboard/import-health` | 文档入库成功率、失败率 | `DASHBOARD_READ` |
| GET | `/api/v1/dashboard/query-health` | 引用覆盖、拒答率、命中率 | `DASHBOARD_READ` |
| GET | `/api/v1/dashboard/recent-events` | 最近任务、日志和风险 | `DASHBOARD_READ` |

查询参数：

- `dateRange=TODAY|LAST_7_DAYS|LAST_30_DAYS|CUSTOM`
- `startDate`
- `endDate`

Dashboard 接口应优先读取聚合表或短缓存，避免实时扫描日志大表。

### 4.3 知识库中心：文档

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/documents` | 文档列表 | `DOCUMENT_READ` |
| GET | `/api/v1/documents/{documentId}` | 文档详情 | `DOCUMENT_READ` |
| PATCH | `/api/v1/documents/{documentId}` | 更新文档标题、元数据 | `DOCUMENT_WRITE` |
| DELETE | `/api/v1/documents/{documentId}` | 删除文档，不再参与新检索 | `DOCUMENT_DELETE` |
| GET | `/api/v1/documents/{documentId}/chunks` | 原文片段列表 | `DOCUMENT_READ` |
| GET | `/api/v1/documents/{documentId}/qa-pairs` | QA 对列表 | `QA_PAIR_READ` |
| POST | `/api/v1/documents/{documentId}/qa-regenerations` | 重新生成 QA 对 | `QA_PAIR_REGENERATE` |
| PATCH | `/api/v1/documents/{documentId}/permissions` | 更新文档访问范围 | `DOCUMENT_PERMISSION_WRITE` |

文档列表筛选：

```http
GET /api/v1/documents?keyword=退款&fileType=PDF&status=READY&departmentId=...&roleId=...&page=1&pageSize=20
```

权限更新请求：

```json
{
  "departmentIds": ["uuid"],
  "roleIds": ["uuid"],
  "userIds": [],
  "allAuthenticated": false
}
```

规则：

- 上传或编辑文档时必须至少设置一个访问范围；为空则仅系统管理员可见。
- 权限变更后新检索立即生效。
- 历史回答引用保留快照，但打开原文详情仍需要当前权限。

### 4.4 知识库中心：上传与任务

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| POST | `/api/v1/import-jobs` | 创建导入任务 | `DOCUMENT_UPLOAD` |
| POST | `/api/v1/import-jobs/{jobId}/files` | 上传或绑定文件 | `DOCUMENT_UPLOAD` |
| GET | `/api/v1/import-jobs/{jobId}` | 查询任务状态 | `DOCUMENT_READ` |
| POST | `/api/v1/import-jobs/{jobId}/retries` | 重试任务 | `TASK_RETRY` |
| DELETE | `/api/v1/import-jobs/{jobId}` | 取消或删除失败任务 | `DOCUMENT_UPLOAD` |
| GET | `/api/v1/task-runs` | 任务运行记录 | `LOG_READ` |
| GET | `/api/v1/task-runs/{taskRunId}` | 任务详情 | `LOG_READ` |

创建导入任务：

```json
{
  "title": "退款流程 SOP V3",
  "permission": {
    "departmentIds": ["uuid"],
    "roleIds": ["uuid"],
    "allAuthenticated": false
  },
  "parseOptions": {
    "preferredParser": "MINERU",
    "enableOcr": true,
    "enableTableStructure": true,
    "fallbackEnabled": true
  },
  "processingOptions": {
    "enableQaSplit": true,
    "enableEmbedding": true
  }
}
```

失败时必须返回 `errorCode`、`errorMessage`、`failedStage` 和 `retryable`。

### 4.5 Chat 问答

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/chat/sessions` | 会话列表 | `CHAT_READ` |
| POST | `/api/v1/chat/sessions` | 创建会话 | `CHAT_WRITE` |
| GET | `/api/v1/chat/sessions/{sessionId}/messages` | 消息列表 | `CHAT_READ` |
| POST | `/api/v1/chat/sessions/{sessionId}/message-runs` | 创建并流式生成回答 | `CHAT_WRITE` |
| POST | `/api/v1/chat/messages/{messageId}/feedback` | 点赞/点踩 | `CHAT_WRITE` |
| GET | `/api/v1/query-runs/{runId}` | 回答运行详情 | `RETRIEVAL_EXPLAIN_READ` |
| GET | `/api/v1/query-runs/{runId}/citations` | 引用列表 | `CHAT_READ` |
| GET | `/api/v1/citations/{citationId}/source` | 引用原文片段 | `CHAT_READ` |

创建回答请求：

```json
{
  "question": "已开票订单怎么退款？",
  "stream": true,
  "retrievalOptions": {
    "vectorTopK": 20,
    "keywordTopK": 20,
    "rerankTopK": 5
  }
}
```

非流式回答响应：

```json
{
  "runId": "run_20260705_001",
  "messageId": "uuid",
  "answer": "已开票订单可以退款，但必须先完成发票红冲并由财务审核。[1]",
  "citations": [
    {
      "id": "uuid",
      "documentId": "uuid",
      "qaPairId": "uuid",
      "title": "退款流程 SOP V3",
      "pageNo": 4,
      "quote": "已开具发票的订单必须先完成红冲流程...",
      "rank": 1,
      "score": 0.92
    }
  ],
  "requestId": "req_..."
}
```

规则：

- 检索无结果或低于阈值时返回“当前知识库中暂无相关信息”，不展示虚假引用。
- 有答案回答至少返回 1 条引用。
- 引用来源必须来自当前用户有权限访问的文档。
- 模型失败时返回 `MODEL_UNAVAILABLE` 或 SSE `error` 事件，并保留用户问题。

### 4.6 检索解释

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/query-runs/{runId}/retrieval-explanation` | 检索和重排解释 | `RETRIEVAL_EXPLAIN_READ` |

响应示例：

```json
{
  "runId": "run_20260705_001",
  "question": "已开票订单怎么退款？",
  "vectorCandidates": [{ "qaPairId": "uuid", "score": 0.81, "rank": 1 }],
  "keywordCandidates": [{ "qaPairId": "uuid", "score": 0.74, "rank": 2 }],
  "rrfCandidates": [{ "qaPairId": "uuid", "rrfScore": 0.032 }],
  "rerankCandidates": [
    {
      "qaPairId": "uuid",
      "finalScore": 0.92,
      "features": {
        "rrfScore": 0.032,
        "exactHitScore": 0.31,
        "titleScore": 0.16,
        "positionScore": 0.08
      }
    }
  ]
}
```

普通员工只能看到自己可访问文档的解释；管理员可在日志排障页查看完整授权范围内的解释。

### 4.7 模型配置

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/model-providers` | 供应商列表 | `MODEL_CONFIG_READ` |
| POST | `/api/v1/model-providers` | 新增供应商 | `MODEL_CONFIG_WRITE` |
| PATCH | `/api/v1/model-providers/{providerId}` | 更新供应商 | `MODEL_CONFIG_WRITE` |
| POST | `/api/v1/model-providers/{providerId}/connection-tests` | 测试连接 | `MODEL_CONFIG_WRITE` |
| GET | `/api/v1/model-configs` | 模型实例列表 | `MODEL_CONFIG_READ` |
| POST | `/api/v1/model-configs` | 新增模型实例 | `MODEL_CONFIG_WRITE` |
| PATCH | `/api/v1/model-configs/{configId}` | 更新模型实例 | `MODEL_CONFIG_WRITE` |
| PATCH | `/api/v1/model-configs/{configId}/default` | 设置默认模型 | `MODEL_CONFIG_WRITE` |

供应商创建请求：

```json
{
  "providerType": "OPENAI_COMPATIBLE",
  "name": "DeepSeek Gateway",
  "baseUrl": "https://api.example.com/v1",
  "apiKey": "********",
  "config": {
    "organization": null
  }
}
```

Secret 保存后响应只返回：

```json
{
  "id": "uuid",
  "name": "DeepSeek Gateway",
  "secretConfigured": true,
  "updatedAt": "2026-07-05T00:00:00+08:00"
}
```

### 4.8 API Key 与调用日志

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/api-keys` | API Key 列表 | `API_KEY_READ` |
| POST | `/api/v1/api-keys` | 创建 API Key | `API_KEY_WRITE` |
| POST | `/api/v1/api-keys/{keyId}/rotations` | 轮换 API Key | `API_KEY_WRITE` |
| POST | `/api/v1/api-keys/{keyId}/disable` | 禁用 API Key | `API_KEY_WRITE` |
| GET | `/api/v1/api-call-logs` | API 调用日志 | `LOG_READ` |

创建请求：

```json
{
  "name": "Internal Copilot",
  "scopes": ["chat:read", "knowledge:query"],
  "allowedDepartmentIds": ["uuid"],
  "allowedRoleIds": ["uuid"],
  "rateLimitPerMinute": 120,
  "expiresAt": "2026-10-05T00:00:00+08:00"
}
```

创建响应仅首次返回明文：

```json
{
  "id": "uuid",
  "key": "lk_live_xxxxxxxxx",
  "keyPrefix": "lk_live_92fa",
  "warning": "密钥明文只展示一次，请妥善保存。"
}
```

### 4.9 日志、任务与系统设置

| Method | Path | 说明 | 权限 |
| --- | --- | --- | --- |
| GET | `/api/v1/audit-logs` | 审计日志 | `AUDIT_READ` |
| GET | `/api/v1/model-call-logs` | 模型调用日志 | `LOG_READ` |
| GET | `/api/v1/task-runs` | 任务日志 | `LOG_READ` |
| POST | `/api/v1/task-runs/{taskRunId}/retries` | 重试可重试任务 | `TASK_RETRY` |
| GET | `/api/v1/settings` | 系统设置 | `SETTING_READ` |
| PATCH | `/api/v1/settings` | 更新系统设置 | `SETTING_WRITE` |

日志筛选必须支持：

- 时间范围。
- 状态。
- 任务类型。
- 操作人。
- 资源类型。
- `requestId`。
- `runId`。

## 5. OpenAI 兼容 API

### 5.1 Chat Completions

| Method | Path | 说明 | 认证 |
| --- | --- | --- | --- |
| POST | `/v1/chat/completions` | OpenAI 兼容问答 | API Key |

请求示例：

```json
{
  "model": "knowledge-chat",
  "messages": [
    { "role": "user", "content": "已开票订单怎么退款？" }
  ],
  "stream": true,
  "metadata": {
    "departmentId": "uuid",
    "roleIds": ["uuid"]
  }
}
```

非流式响应在 OpenAI 兼容结构中扩展 `citations` 和 `request_id`：

```json
{
  "id": "chatcmpl_uuid",
  "object": "chat.completion",
  "created": 1783180800,
  "model": "knowledge-chat",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "已开票订单可以退款，但必须先完成发票红冲并由财务审核。[1]"
      },
      "finish_reason": "stop"
    }
  ],
  "citations": [
    {
      "document_id": "uuid",
      "qa_pair_id": "uuid",
      "title": "退款流程 SOP V3",
      "page_no": 4,
      "quote": "已开具发票的订单必须先完成红冲流程...",
      "rank": 1,
      "score": 0.92
    }
  ],
  "request_id": "req_..."
}
```

流式响应兼容 `chat.completion.chunk`，引用可作为扩展事件输出：

```text
data: {"id":"chatcmpl_uuid","object":"chat.completion.chunk","choices":[{"delta":{"content":"已开票订单"},"index":0}]}

data: {"type":"citation","citation":{"document_id":"uuid","title":"退款流程 SOP V3","page_no":4,"rank":1}}

data: [DONE]
```

### 5.2 API Key 错误语义

| 条件 | HTTP 状态 | 错误码 |
| --- | --- | --- |
| Key 缺失或格式错误 | 401 | `INVALID_API_KEY` |
| Key 已禁用 | 401 | `API_KEY_DISABLED` |
| Key 已过期 | 401 | `API_KEY_EXPIRED` |
| Scope 不足 | 403 | `API_KEY_FORBIDDEN` |
| 限流 | 429 | `RATE_LIMITED` |
| 模型不可用 | 503 | `MODEL_UNAVAILABLE` |

API 调用不得返回无权限引用。

## 6. 内部 Adapter 接口

### 6.1 模型供应商

```python
class ChatProvider:
    async def stream_chat(self, request: ChatRequest) -> AsyncIterator[ChatDelta]:
        ...

    async def complete_chat(self, request: ChatRequest) -> ChatResponse:
        ...

    async def test_connection(self) -> ConnectionTestResult:
        ...

class EmbeddingProvider:
    dimension: int

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
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

解析器必须输出统一 `ParsedDocument`，包含章节、页码、表格、文本块和警告信息。

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
```

`object_key` 必须相对化，不允许绝对路径、盘符、`..` 和路径穿越。

## 7. API 兼容性规则

- 新增字段必须向后兼容，优先新增可选字段。
- 不删除既有响应字段，不改变字段类型，不复用已废弃枚举含义。
- 列表接口新增筛选条件不能改变默认排序和默认范围。
- 错误响应结构不能按端点变化。
- OpenAPI Schema、前端类型、API 文档必须随接口变更一起提交。
- 外部输入只在边界层校验，内部代码依赖类型契约。
- OpenAI 兼容接口新增扩展字段时必须保持标准客户端可忽略。

## 8. API 验收清单

- [ ] 每个端点都有输入、输出和错误结构。
- [ ] 所有列表端点支持分页。
- [ ] 所有写端点有权限校验和审计日志。
- [ ] 文档检索在 SQL 阶段完成权限过滤。
- [ ] 上传、解析、QA 拆分、Embedding 失败可查询且可重试。
- [ ] Chat SSE 支持 `run_started`、`delta`、`citation`、`done`、`error`。
- [ ] 知识不足时明确拒答且不返回虚假引用。
- [ ] OpenAI 兼容接口支持流式和非流式响应，并返回 `citations` 与 `request_id`。
- [ ] API Key 创建、禁用、轮换、限流和日志可验证。
- [ ] Secret 字段保存后不明文返回。
