# DeepSeek、Chunk 与 Embedding 阶段超时问题对比分析

> 文档编号：006  
> 版本：v1.1  
> 分析日期：2026-08-04  
> 分析问题：非 Ollama 模型供应商（例如 DeepSeek）是否会遇到相同问题；为什么前面的 Chunk 阶段没有出现相同错误；后面的 Embedding 是否也可能超时。

## 1. 结论

### 1.1 DeepSeek 等云端 Chat API 也可能超时

只要 QA Split 通过网络调用外部大模型，就会面临同一类基础风险：

```text
网络连接
TLS/代理
供应商排队
模型推理
响应读取
限流
服务端 5xx
上下文或输出限制
```

所以 DeepSeek 也可能出现：

```text
PROVIDER_CONNECTION_TIMEOUT
PROVIDER_INFERENCE_TIMEOUT
PROVIDER_CONNECTION_ERROR
PROVIDER_RATE_LIMITED
PROVIDER_SERVER_ERROR
```

但根因可能和 Ollama 不同。Ollama 更常见的是本地模型加载、机器资源和网络拓扑；云 API 更常见的是公网网络、供应商排队、限流、模型推理和账户配额。

### 1.2 Chunk 阶段通常没有同样错误

当前 Lingxi 的 Chunk 处理主要是本地确定性处理，不调用 QA Chat 模型。它消费解析器输出，通过规则、Token 预算和层级关系生成 `DocumentChunk`。

因此它不会触发 QA Provider 的 Chat timeout。

### 1.3 Embedding 也可能超时

Embedding 仍然可能调用远程模型 API 或本地 Ollama，因此同样可能出现网络、读取和 Provider 服务错误。但 Embedding 的请求形态、输入数量和失败类型不同，不会出现 QA 专属的 provenance 错误。

## 2. DeepSeek 在当前项目中的调用方式

当前项目没有单独的 DeepSeek Provider 类。DeepSeek 如果提供 OpenAI 兼容接口，应配置为：

```text
provider_type = OPENAI_COMPATIBLE
capability = QA_SPLIT
model_name = 实际 DeepSeek 模型名
base_url = 供应商要求的 API 根地址
```

适配器：

```text
server/app/integrations/model_providers/openai_compatible.py
```

QA 请求：

```text
POST {base_url}/chat/completions
```

核心字段：

```json
{
  "model": "实际模型名",
  "messages": [
    {
      "role": "user",
      "content": "QA Split Prompt ..."
    }
  ],
  "stream": false,
  "max_tokens": 4096,
  "temperature": 0,
  "response_format": {
    "type": "json_object"
  }
}
```

当前适配器对所有 OpenAI 兼容 Provider 使用相同基础协议，因此 DeepSeek 的实际能力必须通过 Provider 配置和真实连接测试确认。

## 3. DeepSeek 可能出现的超时根因

### 3.1 公网连接或代理问题

与本地 Ollama 不同，DeepSeek 请求通常经过：

```text
本地 Worker
  -> 公司代理或网关
  -> 公网 DNS
  -> TLS
  -> 供应商 API Gateway
  -> 模型服务
```

任意一层都可能导致：

```text
ConnectTimeout
ReadTimeout
TransportError
```

### 3.2 供应商排队和限流

云 API 可能在服务端排队。HTTP 连接本身已经成功，但模型响应迟迟没有返回。也可能直接返回 429 或 5xx。

这种情况应区分：

```text
PROVIDER_INFERENCE_TIMEOUT
PROVIDER_RATE_LIMITED
PROVIDER_SERVER_ERROR
```

不能把所有问题都显示成“连接失败”。

### 3.3 推理或 reasoning 模式耗时

某些模型可能默认启用较长的 reasoning/thinking 过程。当前通用 OpenAI 兼容适配器没有统一发送：

```text
thinking
reasoning_effort
```

之类的供应商专属字段。若目标模型默认进行额外推理，QA Split 可能比普通 Chat 更慢。

后续应允许在 Provider 配置中通过白名单传递供应商支持的推理控制字段，并为不同模型设置不同 timeout 和输出预算。

### 3.4 JSON 输出和上下文限制

当前 OpenAI 兼容适配器使用：

```json
{
  "response_format": {
    "type": "json_object"
  }
}
```

这通常约束 JSON 形式，但不一定强制完整的 QA provenance Schema。模型仍可能返回：

- `items` 不是数组；
- 缺少 `coveredChunkIndexes`；
- 缺少 `skippedChunks`；
- `finish_reason = length` 导致 JSON 截断；
- `quote` 和 Chunk 原文不匹配。

这些问题不是网络 timeout，但可能发生在同一个长 Prompt 场景中。

## 4. 为什么前面的 Chunk 阶段没有同样 timeout

### 4.1 当前流水线边界

当前主链路：

```text
PDF
  -> Document Parser
  -> Parsed Markdown
  -> Chunking
  -> QA Split Chat Model
  -> Embedding Model
  -> Indexing
```

### 4.2 PDF 解析和 Chunking 是不同组件

PDF 解析由 Parser 服务负责，例如：

```text
server/app/services/document_parse_service.py
server/app/integrations/parsers/mineru.py
server/app/integrations/parsers/docling.py
```

解析器可能本身使用 OCR、版面识别或外部服务，但 Lingxi 对它们配置的是：

```text
MINERU_TIMEOUT_MS
MINERU_MAX_WAIT_SECONDS
DOCLING_TIMEOUT_MS
DOCLING_MAX_WAIT_SECONDS
```

这些 timeout 与 QA ModelConfig 的 `timeout_ms` 无关。

### 4.3 Chunking 主要是本地处理

Chunking 负责：

1. 清洗和规范化解析文本；
2. 合并相邻块；
3. 按 Token 预算切分；
4. 生成 Parent/Child 关系；
5. 保存页码、标题路径和来源定位；
6. 写入数据库。

文件：

```text
server/app/services/chunking/service.py
server/app/services/document_parse_service.py
```

它不调用：

```text
adapter.generate_qa_pairs()
```

所以不会有 QA Chat 的模型读取超时。

### 4.4 Chunk 阶段仍可能有其他错误

Chunk 阶段不是永远不会失败，它可能因为以下原因失败：

- Parser 服务连接或轮询超时；
- PDF 内容损坏；
- OCR 失败；
- Tokenizer 不可用；
- 数据库写入失败；
- Adaptive Chunk 配置不合法；
- Chunk generation 写入冲突。

但它们的错误码和调用链不同，不能和 QA Provider timeout 混为一谈。

## 5. Embedding 是否会出现同样问题

会。Embedding 仍然是外部模型调用，只是 API 和数据处理方式不同。

### 5.1 Embedding 模型独立选择

文件：

```text
server/app/services/embedding_service.py
```

函数：

```text
EmbeddingService._default_model()
```

它只选择：

```text
ModelConfig.capability = EMBEDDING
is_default = true
status = ACTIVE
```

QA Split 模型不会自动作为 Embedding 模型使用。即使 QA 使用 DeepSeek Chat，Embedding 也应配置一个真正支持 Embedding 的模型和 Provider。

### 5.2 Embedding 请求形式

OpenAI 兼容 Provider：

```text
POST {base_url}/embeddings
```

请求一个输入列表：

```json
{
  "model": "embedding-model",
  "input": ["文本 1", "文本 2"]
}
```

Ollama Provider：

```text
POST {base_url}/api/embeddings
```

当前实现对每个文本逐个调用 Ollama Embedding 接口。

### 5.3 Embedding 默认批处理和重试

当前配置：

```text
EMBEDDING_BATCH_SIZE=64
EMBEDDING_MAX_CONCURRENCY=4
EMBEDDING_BATCH_MAX_RETRIES=2
```

Embedding Service 会：

1. 构造 QA Embedding targets；
2. 如果启用 Chunk indexing，再构造 Child Chunk targets；
3. 按 batch size 分批；
4. 使用 `run_ordered()` 并发；
5. 对可重试的 ProviderError 做批次级退避；
6. 校验返回数量；
7. 校验向量维度；
8. 最后统一写入向量和搜索文本。

### 5.4 Embedding 可能的错误

| 错误类型 | 示例 |
|---|---|
| 连接超时 | Provider 无法连接 |
| 推理读取超时 | Embedding 服务响应过慢 |
| 限流 | 429 |
| 服务端错误 | 5xx |
| 输入过长 | `EMBEDDING_INPUT_TOO_LONG` |
| 返回数量不匹配 | `EMBEDDING_RESULT_COUNT_MISMATCH` |
| 维度不匹配 | `EMBEDDING_DIMENSION_MISMATCH` |
| 没有 QA 对 | `EMBEDDING_NO_QA_PAIRS` |
| generation 变化 | `EMBEDDING_RUN_CONFIG_CHANGED` |

Embedding 不会产生：

```text
QA_PROVENANCE_CONTRACT_INVALID
```

因为它不解析 QA JSON，也不校验 `items`、quote、pageNo 或 covered/skipped。

## 6. QA Split 与 Embedding 的核心差异

| 对比项 | QA Split | Embedding |
|---|---|---|
| 能力 | `QA_SPLIT` | `EMBEDDING` |
| 输入 | Chunk + Prompt | QA question，及可选 Chunk 文本 |
| 输出 | JSON QA 文档 | 向量数组 |
| 主要风险 | 推理耗时、JSON、provenance | 超时、数量、维度、输入长度 |
| Provider 接口 | Chat/Completions | Embeddings |
| 输出可验证性 | 结构和来源多重验证 | 数量和维度验证 |
| 失败后状态 | `QA_SPLITTING` / `FAILED` | `EMBEDDING` 或 `INDEXING` / `FAILED` |
| 重试粒度 | 当前是批次结果触发任务重试 | 已有批次内 Provider 重试 |
| 最终数据 | `QaPair` | `question_embedding`、Chunk embedding、search_text |

## 7. DeepSeek QA 与 Embedding 配置建议

### 7.1 QA Split

```text
Provider type: OPENAI_COMPATIBLE
Capability: QA_SPLIT
Model: 实际支持 Chat 的 DeepSeek 模型
Base URL: 供应商要求的 API 根地址
Timeout: 根据压测设置
Max tokens: 足够生成完整 JSON
Temperature: 0 或较低值
```

同时确认：

```text
response_format=json_object
```

是否被目标 API 支持。如果不支持，应由适配器按 Provider 配置关闭该字段，而不是让请求直接失败。

### 7.2 Embedding

不要因为 QA 使用 DeepSeek Chat，就默认把同一个 ModelConfig 用作 Embedding。应单独配置：

```text
Capability: EMBEDDING
Model: 真正支持 Embedding 的模型
Embedding dimension: 与数据库向量列一致
Batch size: 根据供应商限制设置
```

如果供应商只提供 Chat，不提供 Embedding Endpoint，应配置其他 Embedding Provider。

### 7.3 Ollama Embedding

如果使用 Ollama Embedding：

1. `provider_type` 仍为 `OLLAMA`；
2. ModelConfig capability 为 `EMBEDDING`；
3. `model_name` 必须是已安装的 Embedding 模型；
4. 不能直接使用仅适合 Chat 的 Gemma QA 配置；
5. 需要注意当前实现是逐条调用 `/api/embeddings`，长文档会产生较多请求。

## 8. 当前代码中的重要风险点

### 8.1 OpenAI 兼容响应异常路径

文件：

```text
server/app/integrations/model_providers/openai_compatible.py
```

`_extract_message()` 当前标记为 `@staticmethod`，但错误分支引用了 `self`。如果 DeepSeek 返回：

```text
缺少 choices
缺少 message.content
```

本应返回 `PROVIDER_BAD_RESPONSE`，但可能因 `self` 未定义而变成内部异常，最终被 QA Service 包装为：

```text
QA_SPLIT_INTERNAL_ERROR
```

应修复为实例方法，确保 Provider 上下文可以正确附加到异常。

### 8.2 finish_reason 未充分检查

当前主要读取：

```text
choices[0].message.content
```

还应检查：

```text
choices[0].finish_reason
```

如果为 `length`，应给出输出截断诊断，而不是让后续 JSON 校验承担全部责任。

### 8.3 OpenAI 兼容 JSON Schema 能力差异

`response_format={"type":"json_object"}` 不能保证所有 Provider 都严格执行完整 QA Schema。应：

1. 根据 Provider 能力配置；
2. 对支持 JSON Schema 的模型使用更强约束；
3. 对不支持 Schema 的模型降低批次、降低温度并增强 Prompt；
4. 保留后端 provenance 校验作为最终防线。

## 9. 故障定位顺序

### QA Split

```text
ModelCallLog
  -> provider_id/model_config_id
  -> error_code
  -> endpoint/model_name
  -> timeout_phase
  -> batch size/concurrency
  -> Provider 实际服务状态
```

### Chunk

```text
Parser Provider
  -> parser timeout
  -> PDF/Markdown 内容
  -> tokenizer/chunk policy
  -> database transaction
```

### Embedding

```text
Embedding ModelConfig
  -> batch size/concurrency
  -> Provider timeout/rate limit
  -> result count
  -> vector dimension
  -> generation binding
  -> final persistence
```

## 10. 最终判断

1. DeepSeek 等非 Ollama Chat Provider 也会遇到长耗时和 timeout，只是网络和供应商侧因素更多。
2. Chunk 阶段没有遇到相同 QA timeout，是因为当前 Chunking 主要是本地确定性处理，不调用 QA Chat 模型。
3. PDF Parser 可能有自己的外部服务 timeout，但它与 QA ModelConfig timeout 是两条独立链路。
4. Embedding 也可能 timeout，且在远程 API、Ollama、本地资源或限流场景下都可能发生。
5. Embedding 不会产生 QA provenance 错误，但会产生输入长度、数量和向量维度错误。
6. QA 和 Embedding 必须按 capability 分别配置模型，不能默认共享同一个 Chat 模型。
7. 最终可检索条件仍然是：

```text
QA Split 成功
  -> Embedding 成功
  -> Indexing 成功
  -> Document.status = READY
  -> ImportJob.status = COMPLETED
```

