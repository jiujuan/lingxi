# QA Split 长耗时模型调用超时治理方案

> 文档编号：005  
> 版本：v1.1  
> 分析日期：2026-08-04  
> 目标：解决 QA Split 内容较多、模型推理时间较长时，timeout 设置过短导致失败，设置过长又降低故障发现速度的问题。

## 1. 问题本质

QA Split 的一次模型调用同时承担：

1. 读取较长的 Chunk Prompt；
2. 理解文档内容；
3. 生成多个问题和答案；
4. 生成原文 quote；
5. 生成 pageNo 和 chunkIndex；
6. 生成 covered/skipped 覆盖信息；
7. 输出完整 JSON。

因此模型耗时与以下因素相关：

```text
输入 Token 数
输出 Token 数
模型推理速度
模型是否冷启动
供应商排队时间
网络延迟
并发请求数
是否启用 reasoning/thinking
```

固定一个很小的 timeout 会误杀正常长任务；固定一个很大的 timeout 会导致网络故障、死连接和错误配置长时间占用 Worker。

正确方向不是单纯把 timeout 无限增大，而是把“请求规模、并发、超时预算、重试、断点恢复”一起治理。

## 2. 方案总览

推荐采用多层方案：

| 层次 | 方案 | 主要解决问题 |
|---|---|---|
| L1 | 控制单批次输入和输出规模 | 避免单次调用过重 |
| L2 | 控制 QA 并发和资源背压 | 避免本地/云端排队 |
| L3 | 分离连接、读取和总时限 | 准确识别失败阶段 |
| L4 | 批次级重试与超时拆分 | 单批次失败不拖垮整篇文档 |
| L5 | 批次级 checkpoint | 长任务可恢复，不重复全部调用 |
| L6 | Provider 专属参数和路由 | 适配 Ollama、DeepSeek 等差异 |
| L7 | 调用观测和动态调参 | 用数据而不是猜测设置 timeout |

## 3. L1：控制单批次规模

### 3.1 当前机制

文件：

```text
server/app/services/qa_split_service.py
```

函数：

```text
QaSplitService._group_chunks()
```

默认：

```text
QA_SPLIT_MAX_BATCH_CHARS=6000
```

当前算法按 Chunk 正文字符数贪心分组。它是近似 Token 预算，不是严格 Token 预算。

### 3.2 推荐调整

对于本地 Gemma/Ollama：

```text
QA_SPLIT_MAX_BATCH_CHARS=2000-4000
QA_SPLIT_MAX_CONCURRENCY=1-2
```

对于响应速度较快、上下文较大的云端模型：

```text
QA_SPLIT_MAX_BATCH_CHARS=4000-8000
QA_SPLIT_MAX_CONCURRENCY=2-4
```

实际值应根据模型上下文窗口、Prompt 固定开销和平均输出长度压测。

### 3.3 为什么不能只看正文字符数

一个 QA Prompt 的实际输入还包括：

```text
系统说明
输出 JSON Schema
文档标题
标题路径
Chunk 元数据
Chunk 正文
```

输出还包括：

```text
question
answer
quote
pageNo
chunkIndex
coveredChunkIndexes
skippedChunks
```

因此建议将字符预算逐步改为：

```text
估算输入 Token + 预估最大输出 Token <= 模型上下文预算
```

如果暂时不能使用模型专用 Tokenizer，至少为 JSON 和 Prompt 预留固定安全系数。

## 4. L2：并发和背压

### 4.1 当前机制

QA Split 使用：

```text
run_ordered(groups, generate, settings.qa_split_max_concurrency)
```

默认并发为 4。

### 4.2 本地 Ollama 的建议

本地部署不能简单套用云 API 并发值。需要考虑：

- CPU 核数；
- GPU 显存；
- 模型参数量；
- Ollama 是否允许并行推理；
- 是否发生模型卸载和重新加载；
- 同时是否有其他聊天请求。

Gemma QA Split 的初始建议：

```text
QA_SPLIT_MAX_CONCURRENCY=1
```

压测稳定后再提高到 2。只有在确认延迟、内存和显存都稳定时，才考虑 3 或 4。

### 4.3 云 API 的建议

云 API 并发主要受：

- RPM；
- TPM；
- 并发请求上限；
- 单请求上下文；
- 供应商队列；
- 账户计费和限流策略；

影响。并发过高会增加 429、服务端排队和整体尾延迟。

### 4.4 动态背压

后续可以根据错误码动态降低并发：

```text
429 / 503 / 推理 timeout
    -> 降低当前文档并发
    -> 退避
    -> 重新提交
连续成功若干批次
    -> 缓慢恢复并发
```

不要在同一篇文档失败后立即用相同并发和相同批次重新提交。

## 5. L3：分离 timeout 预算

### 5.1 当前限制

当前 Provider 使用：

```python
httpx.Client(timeout=self.timeout_seconds)
```

这会把一个配置值同时应用到多个 HTTP 阶段，无法准确回答：

```text
是连接不上，还是模型还在推理？
```

### 5.2 推荐配置模型

新增逻辑配置：

```text
connect_timeout_ms
write_timeout_ms
read_idle_timeout_ms
overall_timeout_ms
```

含义：

| 配置 | 含义 |
|---|---|
| `connect_timeout_ms` | 建立 TCP/TLS/代理连接的最大时间 |
| `write_timeout_ms` | 发送 Prompt 请求体的最大时间 |
| `read_idle_timeout_ms` | 两个响应数据块之间允许的最大空闲时间 |
| `overall_timeout_ms` | 一次调用从开始到结束的总预算 |

### 5.3 推荐初始值

本地 Ollama：

```text
connect_timeout_ms = 5000
write_timeout_ms = 30000
read_idle_timeout_ms = 180000
overall_timeout_ms = 240000
```

云端 Chat API：

```text
connect_timeout_ms = 10000
write_timeout_ms = 30000
read_idle_timeout_ms = 120000
overall_timeout_ms = 180000
```

这些只是初始值，不是所有模型的固定标准。

### 5.4 为什么需要 read idle timeout

长推理模型可能在一段时间后才返回第一个 Token，也可能以流式方式持续返回 Token。固定的“总读取时间”会误判正常慢模型；只设置很大的 overall timeout 又会放过卡死连接。

更合理的方式是：

```text
首 Token 等待时间单独控制
后续 Token 之间的空闲时间单独控制
整个请求总时间仍有上限
```

## 6. L4：批次级重试和超时拆分

### 6.1 当前状态

QA Split 使用批次并发调用。任何一个批次失败，整个 QA Split 任务失败，之后由 Celery 根据 `retryable` 决定重试。

当前适合重试的错误包括：

```text
PROVIDER_CONNECTION_TIMEOUT
PROVIDER_INFERENCE_TIMEOUT
PROVIDER_CONNECTION_ERROR
PROVIDER_RATE_LIMITED
PROVIDER_SERVER_ERROR
```

### 6.2 推荐的超时拆分策略

单个批次出现推理 timeout 时：

1. 第一次：使用原批次重试一次；
2. 第二次：将批次拆成两半；
3. 子批次分别调用；
4. 子批次成功后合并结果；
5. 仍失败则标记该文档失败，并保留批次定位信息。

示意：

```text
Batch [0,1,2,3,4,5]
      timeout
      -> [0,1,2] + [3,4,5]
```

### 6.3 不适合自动重试的错误

以下错误通常应先修配置或 Prompt：

```text
QA_PROVENANCE_CONTRACT_INVALID
QA_SPLIT_INVALID_OUTPUT
QA_SPLIT_MODEL_NOT_CONFIGURED
PROVIDER_UNAUTHORIZED
PROVIDER_REQUEST_ERROR
```

结构错误可以允许一次“修复 Prompt 重试”，但不应无限重试相同输入。

## 7. L5：批次级 checkpoint

### 7.1 为什么需要 checkpoint

当前 QA Split 只在全部批次成功后替换 QA 对。如果 100 个批次处理到第 99 个失败，重新任务会重新调用前 98 个批次，成本和时间都很高。

### 7.2 推荐数据结构

可以新增 QA Split Run 和 QA Split Batch 表，或先扩展任务 options：

```json
{
  "qaSplit": {
    "runId": "...",
    "batchCount": 100,
    "completedBatches": [0, 1, 2],
    "failedBatch": 99,
    "chunkGenerationHash": "...",
    "modelConfigId": "..."
  }
}
```

更稳妥的正式模型应保存：

```text
run_id
document_id
batch_index
chunk_indexes
input_hash
model_config_id
provider_id
status
validated_output
error_code
latency_ms
```

### 7.3 事务原则

checkpoint 不能让未完成的 QA 对进入最终检索集合。推荐：

```text
批次结果 -> 临时 QA Split Run
全部批次成功 -> 一次性发布为 ACTIVE QaPair
```

这样既能断点恢复，也不破坏当前“完整成功后统一替换”的数据一致性。

## 8. L6：Provider 专属策略

### 8.1 Ollama

建议：

1. 服务启动后预热目标模型；
2. 连接测试使用真实模型 Chat；
3. QA 使用结构化 Schema；
4. 温度设置为 0；
5. 单独控制并发；
6. 使用较长推理读取预算；
7. Worker 与 Ollama 的地址必须按实际网络拓扑配置。

### 8.2 OpenAI 兼容云 API

建议：

1. 使用 `response_format` 或供应商支持的 `json_schema`；
2. 明确 `max_tokens`；
3. 对 429 和 5xx 使用退避；
4. 对 reasoning/thinking 模型显式配置推理模式；
5. 检查 `finish_reason`；
6. 记录 usage、latency 和 model name。

### 8.3 DeepSeek 类模型

如果模型默认启用 reasoning，QA Split 输出可能更慢。当前通用 OpenAI 兼容适配器只发送：

```text
model
messages
stream
max_tokens
temperature
response_format
```

没有通用的 `thinking` 或 reasoning effort 字段。后续应将供应商专属参数做成白名单配置，避免把未知参数发送给不支持的模型。

## 9. L7：根据观测数据调参

当前 `ModelCallLog` 已记录：

```text
provider_id
model_config_id
capability
status
latency_ms
error_code
error_message
run_id
```

后续应增加安全的计数指标：

```text
batch_index
input_char_count
estimated_input_tokens
output_char_count
estimated_output_tokens
retry_count
timeout_phase
```

不要记录 Prompt 正文和完整模型输出。

建议按模型统计：

```text
P50 latency
P95 latency
P99 latency
timeout rate
retry success rate
invalid JSON rate
provenance contract failure rate
```

timeout 应按 Provider、模型、批次规模和并发分别观察，不能只看全局平均值。

## 10. 推荐分阶段实施顺序

### 阶段一：立即缓解

适用于当前 Gemma/Ollama 故障：

```text
QA timeout = 180000ms
QA_SPLIT_MAX_BATCH_CHARS = 3000-4000
QA_SPLIT_MAX_CONCURRENCY = 1-2
maxTokens 设置为足够生成完整 JSON
预热 gemma3
重启 QA Worker
```

### 阶段二：增强 Provider HTTP 层

实现：

1. `httpx.Timeout(connect=..., write=..., read=..., pool=...)`；
2. overall deadline；
3. 首 Token 和 read idle 监控；
4. 流式响应聚合；
5. `finish_reason` 检查；
6. 更细的错误码。

### 阶段三：增强 QA 批处理

实现：

1. Token 预算分组；
2. 超时后自动二分批次；
3. 批次级 retry；
4. 动态降低并发；
5. 批次定位信息。

### 阶段四：增强恢复能力

实现：

1. QA Split Run；
2. 批次 checkpoint；
3. 临时结果与最终发布分离；
4. 从失败批次继续；
5. Provider 或 ModelConfig 发生变化时使旧 Run 失效。

## 11. 不同方案的取舍

| 方案 | 优点 | 缺点 |
|---|---|---|
| 直接增大 timeout | 改动小 | 故障发现慢，无法解决过大批次 |
| 减小批次 | 稳定、容易实施 | HTTP 请求数和模型调用成本增加 |
| 降低并发 | 适合本地模型 | 总耗时可能增加 |
| 流式调用 | 可识别模型持续输出 | JSON 聚合和错误处理更复杂 |
| 超时后二分 | 单批次失败影响小 | 需要保持来源和顺序 |
| checkpoint | 长文档恢复成本低 | 需要新的持久化模型和发布事务 |
| 动态调度 | 适应不同模型 | 参数和监控复杂度增加 |

推荐组合：

```text
减小批次 + 降低并发 + 分离 timeout + 批次重试
```

长文档和高价值生产场景再增加：

```text
checkpoint + 断点恢复 + 动态调度
```

## 12. 验收指标

方案实施后至少验证：

1. 短文档在正常模型响应时间内成功；
2. 长文档不会因为单个大批次拖垮整个任务；
3. 连接失败能快速返回；
4. 模型推理慢时有清晰的 inference timeout；
5. timeout 重试不会无限循环；
6. QA provenance 错误不会被误判为网络错误；
7. 失败时能定位 Provider、模型、Endpoint、批次和 timeout phase；
8. Embedding 不会读取未完整发布的 QA 对；
9. `Document` 只有在 Embedding 和 Indexing 完成后才进入 `READY`。

