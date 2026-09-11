# QA Split Provider 诊断能力改进分析

> 文档编号：003  
> 版本：v1.1  
> 分析日期：2026-08-04  
> 目的：记录 QA Split 模型调用错误信息、连接测试和调用审计的改进内容，以及当前仍存在的限制。

## 1. 改进背景

旧版错误：

```text
PROVIDER_CONNECTION_ERROR
模型供应商连接失败：timed out
```

这个错误信息无法回答以下问题：

1. 哪个 Provider 失败；
2. 使用的是哪个模型；
3. 实际请求了哪个 Endpoint；
4. 是建立连接超时，还是模型推理响应超时；
5. 任务到底有没有使用“模型配置”页面选中的配置；
6. 哪一个 QA 批次失败；
7. 是否需要重试，还是配置本身有问题。

本次改进围绕五个方面展开：

1. 扩展 `ProviderError` 上下文；
2. 区分连接超时和推理读取超时；
3. QA Split 写入 `ModelCallLog`；
4. 连接测试支持指定 ModelConfig，并实际调用模型；
5. 页面可以显示 Provider、模型、Endpoint 和 timeout 信息。

## 2. ProviderError 统一错误契约

文件：

```text
server/app/integrations/model_providers/base.py
```

`ProviderError` 当前包含：

| 字段 | 含义 |
|---|---|
| `code` | 稳定错误码 |
| `message` | 已格式化的安全用户可见信息 |
| `base_message` | 不包含上下文的基础描述 |
| `retryable` | 是否允许任务层重试 |
| `status_code` | HTTP 状态码 |
| `provider_name` | Provider 展示名称 |
| `provider_type` | Provider 类型 |
| `model_name` | 实际模型名称 |
| `endpoint` | 实际请求 Endpoint |
| `timeout_ms` | 当前模型配置的 timeout |
| `timeout_phase` | 超时阶段 |

### 2.1 用户可见消息格式

当上下文完整时，错误消息会类似：

```text
模型推理响应失败：timed out
（供应商：Gemma；模型：gemma3；类型：Ollama；
endpoint：http://localhost:11434/api/chat；超时：180 秒读取超时）
```

API 返回也包含结构化字段，不应要求前端从中文错误消息中解析信息。

### 2.2 错误码分类

| 错误码 | 适用情况 | 默认重试 |
|---|---|---:|
| `PROVIDER_CONNECTION_TIMEOUT` | 连接、连接池或写入阶段超时 | 是 |
| `PROVIDER_INFERENCE_TIMEOUT` | 已连接但读取模型响应超时 | 是 |
| `PROVIDER_CONNECTION_ERROR` | 非 Timeout 的传输失败 | 是 |
| `PROVIDER_UNAUTHORIZED` | 401/403 | 否 |
| `PROVIDER_RATE_LIMITED` | 429 | 是 |
| `PROVIDER_SERVER_ERROR` | 5xx | 是 |
| `PROVIDER_REQUEST_ERROR` | 其他 4xx 或请求格式错误 | 通常否 |
| `PROVIDER_BAD_RESPONSE` | Provider 返回结构不符合适配器协议 | 按具体场景处理 |

### 2.3 仍需注意的实现边界

当前 `HttpProvider` 仍使用：

```python
httpx.Client(timeout=self.timeout_seconds)
```

这是一个统一 timeout，不是完全独立的 connect/write/read/overall 四类预算。错误码已经区分主要超时类型，但 timeout 配置本身还可以进一步精细化，详见：

```text
005-qa-split-long-running-timeout-solutions-v1.1.md
```

## 3. QA Split ModelCallLog

数据模型：

```text
server/app/models/model_config.py
```

表：

```text
model_call_logs
```

QA Split 写入位置：

```text
server/app/services/qa_split_service.py
QaSplitService._generate_qa_items()
QaSplitService._record_qa_model_call()
```

### 3.1 记录粒度

QA Split 不是一次模型调用完整处理整个 PDF，而是：

1. 读取当前有效 Child Chunk；
2. 按字符预算分组；
3. 每个分组单独构造 Prompt；
4. 并发调用 Provider；
5. 每组单独校验输出；
6. 所有批次成功后才替换 QA 对。

因此 `ModelCallLog` 按 QA 批次记录。一份 PDF 产生 5 个 Prompt 批次时，正常应有 5 条 QA ModelCallLog。

### 3.2 记录字段

当前写入：

```text
tenant_id
provider_id
model_config_id
run_id = QA TaskRun.id
capability = QA_SPLIT
status = SUCCESS / FAILED
latency_ms
token_usage = {}
error_code
error_message
request_id
```

原始 Prompt、原始模型输出、API Key 和完整文档内容不写入日志，避免敏感数据泄漏。

### 3.3 失败批次的日志行为

并发批次全部返回后，服务先记录每个批次的调用结果，再按输入顺序处理错误：

```text
批次结果 -> ModelCallLog -> 抛出第一个失败结果 -> TaskRun 失败
```

这样可以知道同一轮中哪些批次成功、哪些批次失败，但 QA 对仍然遵循“全部批次成功后统一替换”的事务边界，不会因为前面批次成功就提前写入部分 QA。

## 4. 指定模型连接测试

### 4.1 API 请求

文件：

```text
server/app/api/v1/model_config.py
server/app/schemas/model_config.py
```

接口：

```text
POST /api/v1/model-providers/{provider_id}/connection-tests
```

请求体可以指定：

```json
{
  "modelConfigId": "<QA_SPLIT ModelConfig ID>"
}
```

### 4.2 Service 行为

文件：

```text
server/app/services/model_config_service.py
```

`test_provider_connection()` 会：

1. 查询 Provider；
2. 查询指定 ModelConfig；
3. 校验 ModelConfig 属于该 Provider；
4. 合并 Provider 和 ModelConfig 配置；
5. 注入 `model_name`、`timeout_ms`、`max_tokens`；
6. 创建真实 Provider 适配器；
7. 有 ModelConfig 时调用 `adapter.test_model_connection()`；
8. 无 ModelConfig 时才调用 Provider 级健康检查；
9. 写入 `ModelCallLog`；
10. 返回结构化诊断结果。

### 4.3 不同测试的含义

| 测试方式 | Ollama 请求 | 能证明什么 |
|---|---|---|
| Provider 级连接测试 | `GET /api/tags` | Ollama 服务进程可访问 |
| 指定模型连接测试 | `POST /api/chat`，带 `model=gemma3` | 指定模型可完成一次 Chat 调用 |
| QA Split 实际调用 | `POST /api/chat`，带完整 QA Prompt 和 Schema | 指定模型能完成真实 QA 输出契约 |

Provider 级连接测试成功，不能证明 Gemma 已加载、能推理，也不能证明 QA JSON contract 能满足。

### 4.4 返回字段

当前响应字段包括：

```json
{
  "success": false,
  "status": "FAILED",
  "latencyMs": 180215,
  "errorCode": "PROVIDER_INFERENCE_TIMEOUT",
  "errorMessage": "模型推理响应失败：timed out（供应商：Gemma；模型：gemma3；类型：Ollama；endpoint：http://localhost:11434/api/chat；超时：180 秒读取超时）",
  "providerName": "Gemma",
  "providerType": "OLLAMA",
  "modelConfigId": "...",
  "modelName": "gemma3",
  "endpoint": "http://localhost:11434/api/chat",
  "timeoutMs": 180000,
  "timeoutPhase": "read"
}
```

## 5. QA Split 任务层错误传递

文件：

```text
server/app/tasks/qa_tasks.py
server/app/tasks/_common.py
server/app/services/qa_split_service.py
```

处理过程：

1. Provider 抛出 `ProviderError`；
2. `QaSplitService.split_import_job_for_task()` 保留 `code`、`message` 和 `retryable`；
3. `_mark_failed()` 写入 `ImportJob`、`Document` 和 `TaskRun.error`；
4. `resolve_task_outcome()` 读取持久化错误；
5. `handle_failure()` 决定 Celery retry 或终止任务。

`TaskRun.error` 结构：

```json
{
  "code": "PROVIDER_INFERENCE_TIMEOUT",
  "message": "模型推理响应失败：timed out（供应商：Gemma；模型：gemma3；类型：Ollama；endpoint：http://localhost:11434/api/chat；超时：180 秒读取超时）",
  "retryable": true,
  "failedAt": "2026-08-04T..."
}
```

日志记录只保留安全后的 ProviderError 消息；未标准化的原始异常不会写入用户可见字段，避免数据库连接串、SQL、API Key 或文档内容泄漏。

## 6. 当前已覆盖的测试

### 6.1 HTTP Provider 测试

文件：

```text
server/tests/test_model_providers_http.py
```

覆盖：

- `ConnectTimeout` 映射为 `PROVIDER_CONNECTION_TIMEOUT`；
- `ReadTimeout` 映射为 `PROVIDER_INFERENCE_TIMEOUT`；
- 错误中包含 Provider、模型、类型、Endpoint、timeout 和 phase；
- 非 Timeout 传输错误不误报为 timeout；
- Ollama 指定模型测试实际调用 `/api/chat`；
- Registry 能区分 Mock 和真实 HTTP Provider。

### 6.2 QA ModelCallLog 测试

文件：

```text
server/tests/test_qa_split_task.py
```

覆盖：

- 每个 QA 批次写入成功日志；
- ProviderError 写入失败日志；
- 失败日志保留 `PROVIDER_INFERENCE_TIMEOUT`；
- 失败日志包含 `Gemma`、`gemma3` 和 `/api/chat`；
- 原始未预期异常不会直接泄漏到日志。

### 6.3 模型连接测试

文件：

```text
server/tests/test_model_config.py
```

覆盖：

- 指定 ModelConfig；
- 确认模型属于当前 Provider；
- 返回 `providerName`、`modelName`、Endpoint 和 timeout；
- 写入模型调用日志。

## 7. 前端显示要求

页面不应只显示：

```text
模型供应商连接失败：timed out
```

建议最少显示：

```text
模型供应商：Gemma
模型：gemma3
类型：Ollama
Endpoint：http://localhost:11434/api/chat
超时：180 秒
阶段：读取模型响应超时
错误码：PROVIDER_INFERENCE_TIMEOUT
```

页面应优先使用 API 的结构化字段：

```text
providerName
providerType
modelName
endpoint
timeoutMs
timeoutPhase
errorCode
errorMessage
```

不要通过解析 `errorMessage` 的中文文本来判断错误阶段。

## 8. 后续可继续改进的事项

### 8.1 分离 overall deadline

当前 timeout 仍然是 HTTP Client 级别配置。后续可增加：

```text
connect_timeout_ms
write_timeout_ms
read_idle_timeout_ms
overall_timeout_ms
```

### 8.2 记录批次定位信息

当前 `ModelCallLog` 有 `run_id`，但没有直接记录：

```text
batch_index
batch_chunk_indexes
input_char_count
output_char_count
```

后续可以记录计数和索引范围，但不记录原文正文。

### 8.3 记录 Token usage

OpenAI 兼容响应或 Ollama 响应能够提供 usage 时，应将输入 Token、输出 Token、总 Token 写入 `token_usage`，用于估算批次大小和耗时关系。

### 8.4 处理 finish_reason

OpenAI 兼容 Provider 当前主要提取 `choices[0].message.content`，还可以检查：

```text
finish_reason = length
```

如果输出因达到 `max_tokens` 被截断，应返回明确的 `PROVIDER_OUTPUT_TRUNCATED` 或 QA contract 错误，而不是等 JSON 校验阶段给出模糊提示。

### 8.5 修复适配器异常路径

当前 `OpenAICompatibleProvider._extract_message()` 定义为 `@staticmethod`，但错误分支引用了 `self`。当 Provider 返回缺少 `choices` 或缺少文本内容时，可能把原本的 `PROVIDER_BAD_RESPONSE` 覆盖为 `NameError`，再被 QA Service 归类为内部错误。

该问题应在后续代码改进中修复为实例方法，或显式传入 Provider 上下文。

