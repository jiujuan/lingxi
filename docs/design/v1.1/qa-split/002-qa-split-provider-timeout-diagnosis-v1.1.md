# QA Split 模型供应商超时故障分析

> 文档编号：002  
> 版本：v1.1  
> 分析日期：2026-08-04  
> 适用场景：文档解析中心中，文档解析和知识切片成功，QA 文档生成阶段失败，页面显示 `PROVIDER_CONNECTION_ERROR` 或超时信息。

## 1. 故障现象

典型页面错误：

```text
PROVIDER_CONNECTION_ERROR
模型供应商连接失败：timed out
```

典型 Celery 日志：

```text
Task server.app.tasks.qa_tasks.split_document_qa_task[...] retry:
Retry in 10.0s: TaskProcessingError(...)
```

用户已在“模型配置”页面配置 Ollama 的 `gemma3` 作为 QA Split 模型，并确认 Ollama 客户端已经启动。

## 2. 结论摘要

该错误不能仅凭旧版 `PROVIDER_CONNECTION_ERROR` 判断为“模型没有用到”。需要沿着实际运行链路确认以下事实：

1. 当前租户是否存在一个有效、默认的 `QA_SPLIT` 模型配置；
2. 该模型配置关联的 Provider 是否为 `OLLAMA`；
3. Worker 读取的数据库、租户和配置是否与页面修改的环境一致；
4. Provider 适配器是否被路由为真实的 `OllamaProvider`，而不是测试用 `MockProvider`；
5. Worker 是否已经重启并加载了包含诊断增强的代码；
6. 超时发生在 TCP 连接阶段，还是模型已收到请求但推理响应读取阶段；
7. Ollama 服务是否能从 Celery Worker 所在机器和网络命名空间访问。

当前代码中，QA Split 不会因为“模型页面选择了 Gemma”就自动调用任意模型。它只选择满足查询条件的默认 `QA_SPLIT` 配置，然后把该配置中的模型名、Provider 类型、Endpoint 和 timeout 传入适配器。

## 3. QA Split 实际模型选择链路

### 3.1 数据库查询条件

文件：

```text
server/app/services/qa_split_service.py
```

函数：

```text
QaSplitService._default_model()
```

查询条件包括：

| 条件 | 作用 |
|---|---|
| `ModelConfig.tenant_id == 当前租户` | 防止使用其他租户的模型 |
| `ModelConfig.capability == "QA_SPLIT"` | 只查 QA Split 能力 |
| `ModelConfig.is_default == true` | 只使用该能力的默认模型 |
| `ModelConfig.status == "ACTIVE"` | 模型配置必须启用 |
| `ModelConfig.deleted_at IS NULL` | 排除软删除配置 |
| `ModelProvider.status == "ACTIVE"` | Provider 必须启用 |
| `ModelProvider.deleted_at IS NULL` | 排除软删除 Provider |

如果没有任何记录，系统返回：

```text
QA_SPLIT_MODEL_NOT_CONFIGURED
未配置默认 QA Split 模型
```

因此，“页面中看到模型配置”与“任务运行时会使用该配置”不是同一件事。还必须确认它被标记为当前租户的 `QA_SPLIT` 默认模型，并且 Provider 和 ModelConfig 都是 `ACTIVE`。

### 3.2 Provider 和 ModelConfig 的合并

`QaSplitService.split_import_job_for_task()` 会把以下内容传入 Provider 工厂：

```text
provider.provider_type
provider.base_url
解密后的 provider.encrypted_api_key
provider.config 与 model_config.config 的合并结果
model_config.model_name
model_config.timeout_ms
model_config.max_tokens
provider.name
```

Provider 配置优先级为：

```text
ModelConfig.config 覆盖 ModelProvider.config
```

模型名称和 timeout 由 ModelConfig 的专用字段显式注入：

```text
model_name = model_config.model_name
timeout_ms = model_config.timeout_ms
```

### 3.3 Provider 适配器路由

文件：

```text
server/app/integrations/model_providers/registry.py
```

真实 Provider 路由如下：

| `provider_type` | 适配器 | QA 接口 |
|---|---|---|
| `OLLAMA` | `OllamaProvider` | `POST {base_url}/api/chat` |
| `OPENAI_COMPATIBLE` | `OpenAICompatibleProvider` | `POST {base_url}/chat/completions` |
| `CLAUDE` | `ClaudeProvider` | Claude Messages API |
| `INTERNAL_GATEWAY` | `InternalGatewayProvider` | 内部 OpenAI 兼容接口 |

以下配置会强制进入 `MockProvider`：

1. `base_url` 为空；
2. `base_url` 以 `mock://` 开头；
3. 配置中存在 `mock: true`；
4. 配置中包含 `chatResponse`、`qaSplitResponse`、`chatError` 或 `testMode` 测试标记。

如果实际配置是一个完整的 Ollama URL，且没有测试标记，则会使用真实 `OllamaProvider`，不会静默改成 Mock。

## 4. Ollama QA Split 请求内容

文件：

```text
server/app/integrations/model_providers/ollama.py
```

`generate_qa_pairs()` 最终调用：

```text
POST {base_url}/api/chat
```

请求核心字段包括：

```json
{
  "model": "gemma3",
  "messages": [
    {
      "role": "user",
      "content": "QA Split Prompt ..."
    }
  ],
  "stream": false,
  "format": {
    "type": "object",
    "properties": {
      "items": { "type": "array" },
      "coveredChunkIndexes": { "type": "array" },
      "skippedChunks": { "type": "array" }
    }
  },
  "options": {
    "temperature": 0
  }
}
```

`format` 使用 QA provenance contract 的结构化 Schema，目的是减少 Gemma 返回 `{}`、字符串或不含数组字段的 JSON。

## 5. 超时发生在哪里

### 5.1 当前 HTTP timeout 的行为

文件：

```text
server/app/integrations/model_providers/base.py
```

`HttpProvider._request_json()` 当前使用一个标量 timeout：

```text
httpx.Client(timeout=self.timeout_seconds)
```

这个配置会同时影响连接、写入、读取等 HTTP 阶段。当前 timeout 不是“允许模型整体执行多久”的精确定义，而是 HTTP 客户端各阶段的超时上限。

### 5.2 当前错误码分类

| 现象 | 当前错误码 | 解释 |
|---|---|---|
| TCP 连接、连接池或写入超时 | `PROVIDER_CONNECTION_TIMEOUT` | 尚未正常建立或发送完请求 |
| 已建立连接，但推理响应读取超时 | `PROVIDER_INFERENCE_TIMEOUT` | 模型可能已经开始推理，但在读取响应时超时 |
| 非 Timeout 的 HTTP 传输错误 | `PROVIDER_CONNECTION_ERROR` | 连接被拒绝、连接重置等传输异常 |
| 401/403 | `PROVIDER_UNAUTHORIZED` | API Key 或权限问题 |
| 429 | `PROVIDER_RATE_LIMITED` | 供应商限流 |
| 5xx | `PROVIDER_SERVER_ERROR` | 供应商服务端故障 |

因此，旧日志中看到的：

```text
PROVIDER_CONNECTION_ERROR: ... timed out
```

可能来自旧 Worker 代码，或者来自未区分 Timeout 类型的旧异常处理。当前代码对于 `httpx.ReadTimeout` 会优先映射为 `PROVIDER_INFERENCE_TIMEOUT`。

## 6. 最可能的根因

### 6.1 Gemma 首次加载或冷启动耗时超过 timeout

Ollama 在第一次调用某个模型时可能需要：

1. 读取模型文件；
2. 将模型加载到内存或显存；
3. 初始化推理运行时；
4. 执行较长 Prompt；
5. 生成完整 JSON。

这时服务端端口是可访问的，但模型没有在 timeout 内返回完整响应。该场景更接近“推理读取超时”，不是“模型配置没有使用”。

### 6.2 QA Prompt 或单批次内容过大

QA Split 会按 `QA_SPLIT_MAX_BATCH_CHARS` 对 Chunk 分批，默认值为 `6000` 字符。一个批次还包含：

- Chunk 正文；
- 文档标题；
- 标题路径；
- 页码和来源信息；
- 输出契约要求；
- QA Prompt 指令。

因此 6000 个正文字符并不等于 6000 个模型 Token。中文、JSON 结构和输出字段都会增加上下文和生成时间。

### 6.3 并发批次过多导致 Ollama 资源争用

默认：

```text
QA_SPLIT_MAX_CONCURRENCY=4
```

如果一个 PDF 产生多个批次，最多会同时发起 4 个模型请求。对于本地 Ollama，尤其是 CPU 推理或显存不足的场景，并发可能导致：

- 单个请求变慢；
- 内存交换；
- GPU 显存竞争；
- Ollama 排队；
- 多个请求同时达到 timeout。

### 6.4 Worker 和 Ollama 不在同一网络位置

“客户端 Ollama 已启动”只说明启动 Ollama 的那台机器可以访问它，不代表 Celery Worker 可以访问它。常见情况：

- API Worker 在 Docker，Ollama 在宿主机；
- Celery Worker 在另一台服务器；
- `localhost` 指向 Worker 容器，而不是 Windows 宿主机；
- Windows 防火墙阻止容器或远端访问；
- Ollama 只监听 `127.0.0.1`；
- 配置中的端口或 base URL 写错。

### 6.5 配置已修改，但执行任务的 Worker 使用了旧环境

任务由 Celery Worker 执行，不是由当前浏览器直接调用。以下问题会造成“页面配置正确但 Worker 实际未使用”：

- Worker 连接了另一套数据库；
- Worker 使用了不同的 `.env`；
- 修改配置后没有重启 Worker；
- Worker 运行的是旧代码；
- 页面和 Worker 使用了不同租户；
- 默认标记被设置到了另一个 QA Split 模型；
- Provider 或 ModelConfig 仍是 `DISABLED`。

### 6.6 真实模型名、Provider 类型或 Endpoint 不一致

例如：

```text
provider_type = OLLAMA
model_name = gemma3
base_url = http://localhost:11434
```

适配器会请求：

```text
http://localhost:11434/api/chat
```

如果把 `/api/chat` 也写进 `base_url`，最终可能拼成错误路径。模型名不存在时通常更可能返回 HTTP 错误，而不是纯 timeout，但仍应检查：

```text
ollama list
```

## 7. 如何判断“配置了但没用到”

建议按以下顺序确认。

### 7.1 确认 ModelConfig

检查数据库或“模型配置”接口返回：

```text
capability = QA_SPLIT
model_name = gemma3
is_default = true
status = ACTIVE
timeout_ms = 180000
```

### 7.2 确认 Provider

检查：

```text
provider_type = OLLAMA
status = ACTIVE
base_url = http://localhost:11434
```

不要将 `/api/chat` 写入 `base_url`。

### 7.3 使用“指定模型连接测试”

连接测试必须传入 `modelConfigId`。传入后，服务会：

1. 校验模型属于当前 Provider；
2. 使用该模型的 `model_name`、timeout 和 config 构造适配器；
3. 调用 `test_model_connection()`；
4. 对 Ollama 实际请求 `/api/chat`；
5. 在响应中返回 Provider、模型、Endpoint、timeout 和 timeout phase。

只测试 `/api/tags` 只能说明 Ollama 进程可访问，不能证明 `gemma3` 可以完成 QA Chat 调用。

### 7.4 检查 ModelCallLog

QA Split 每个批次都会记录一条 `ModelCallLog`，包含：

```text
provider_id
model_config_id
capability = QA_SPLIT
run_id
status
latency_ms
error_code
error_message
request_id
```

如果日志中出现：

```text
provider_id = Ollama Provider
model_config_id = gemma3 的 ModelConfig
capability = QA_SPLIT
```

就可以确认任务已经选中了该配置。错误消息还应包含 Gemma、`gemma3`、`OLLAMA` 和 `/api/chat`。

### 7.5 检查 Worker 日志和版本

修改模型配置后，建议重启：

```text
Celery QA Worker
```

并确认 Worker 使用的代码版本包含：

```text
PROVIDER_CONNECTION_TIMEOUT
PROVIDER_INFERENCE_TIMEOUT
provider_name
model_name
endpoint
timeout_phase
```

如果仍然只显示“连接失败：timed out”，很可能是旧 Worker 没有重启，或错误来自未统一处理的旧代码路径。

## 8. 推荐的现场处理步骤

1. 在 Worker 所在机器上测试 Ollama Endpoint，而不是只在浏览器所在机器测试。
2. 确认 `base_url` 为 Ollama 根地址，例如 `http://localhost:11434`。
3. 确认 `ollama list` 中存在 `gemma3`。
4. 使用指定 `modelConfigId` 执行连接测试。
5. 将 QA Split timeout 临时提高到 `180000ms`。
6. 将 `QA_SPLIT_MAX_CONCURRENCY` 临时降为 `1` 或 `2`。
7. 将 `QA_SPLIT_MAX_BATCH_CHARS` 临时降到 `3000-4000`。
8. 先执行一次短 PDF 或单 Chunk 测试。
9. 重启 QA Worker。
10. 重新执行失败任务，并查看 `ModelCallLog`、`TaskRun.error` 和 Worker 日志。

## 9. 验收判断

只有满足以下条件，才能确认是“模型推理超时”而不是“没有使用配置模型”：

- `ModelCallLog.model_config_id` 指向 Gemma 的 QA_SPLIT ModelConfig；
- `ModelCallLog.provider_id` 指向 Ollama Provider；
- `error_code = PROVIDER_INFERENCE_TIMEOUT`；
- `error_message` 包含模型、Provider 类型和 `/api/chat`；
- 指定模型连接测试能访问同一个 Endpoint；
- 降低批次大小或并发后，短文档能够成功完成 QA Split。

如果 `ModelCallLog` 指向的不是 Gemma 配置，优先排查默认模型、租户、数据库和 Worker 环境；如果指向 Gemma 且是 `PROVIDER_INFERENCE_TIMEOUT`，优先排查推理耗时、批次大小、并发和资源配置。

