# QA_PROVENANCE_CONTRACT_INVALID：items 必须是数组

> 文档编号：004  
> 版本：v1.1  
> 分析日期：2026-08-04  
> 适用错误：`QA_PROVENANCE_CONTRACT_INVALID`，页面消息为“QA 拆分输出 items 必须是数组”。

## 1. 错误含义

该错误表示：

1. QA 模型已经返回了可以被解析的 JSON；
2. JSON 顶层通常是一个对象；
3. 但顶层对象中的 `items` 字段不是 JSON 数组。

期望结构：

```json
{
  "items": [
    {
      "question": "问题",
      "answer": "答案",
      "quote": "原文引用",
      "pageNo": 1,
      "chunkIndex": 0
    }
  ],
  "coveredChunkIndexes": [0],
  "skippedChunks": []
}
```

错误结构示例：

```json
{
  "items": {
    "question": "问题",
    "answer": "答案"
  }
}
```

```json
{
  "items": "没有生成 QA"
}
```

```json
{
  "items": null
}
```

```json
{
  "question": "问题",
  "answer": "答案"
}
```

最后一种结构甚至没有 `items` 字段，会触发“缺少 items 数组”的相邻错误。

## 2. 当前代码校验位置

文件：

```text
server/app/services/qa_split_service.py
```

函数：

```text
validate_qa_split_output()
```

校验顺序：

```text
原始文本
  -> _extract_json_text()
  -> json.loads()
  -> 顶层必须是 dict
  -> 必须存在 items
  -> items 必须是 list
  -> 每个 item 必须是 dict
  -> question/answer/quote/pageNo/chunkIndex 校验
  -> 来源 Chunk 校验
  -> covered/skipped 覆盖契约校验
```

关键逻辑：

```python
items = parsed.get("items")
if not isinstance(items, list):
    raise _provenance_error(
        QA_PROVENANCE_CONTRACT_INVALID,
        (
            "QA 拆分输出 items 必须是数组，"
            f"实际类型为 {_json_type_name(items)}"
        ),
        retryable=False,
    )
```

因此，错误不是数据库错误，也不是 Embedding 错误，而是模型响应违反了 QA Split 输出协议。

## 3. 为什么 Gemma/Ollama 会产生这个错误

### 3.1 JSON 模式不等于业务 Schema

只要求模型返回 JSON，通常只能保证：

```text
输出语法是 JSON
```

不能保证：

```text
顶层一定有 items
items 一定是数组
数组元素一定包含所有字段
来源索引一定正确
coveredChunkIndexes 和 skippedChunks 一定完整
```

例如模型返回 `{}` 是合法 JSON，但不满足 QA provenance contract。

### 3.2 Prompt 契约没有被模型稳定遵守

即使 Prompt 写明了目标结构，模型仍可能：

- 把单个 QA 对直接放在 `items` 对象中；
- 只返回一个 `question/answer` 对象；
- 返回解释文本或 Markdown；
- 返回 `items: null`；
- 忽略 `coveredChunkIndexes` 和 `skippedChunks`；
- 输出不完整 JSON。

### 3.3 模型或 Worker 仍使用旧代码

当前 Ollama 适配器已经在 `generate_qa_pairs()` 中使用结构化 Schema：

```text
payload["format"] = _QA_SPLIT_OUTPUT_SCHEMA
```

同时设置：

```text
temperature = 0
```

如果代码修改后没有重启 Celery QA Worker，仍可能使用旧版本：

```text
payload["format"] = "json"
```

旧 JSON 模式只能减少非 JSON 文本，不能强制 `items` 为数组。

### 3.4 Prompt 批次或输出长度过大

当输入批次过大时，模型可能：

- 只处理部分 Chunk；
- 输出被 `max_tokens` 截断；
- 为了节省输出，返回简化结构；
- 在长响应末尾损坏 JSON。

此时即使模型本身支持 JSON，也不代表能稳定满足完整 Contract。

## 4. 当前 QA Contract

### 4.1 顶层对象

必须是 JSON object，并且包含：

```text
items
coveredChunkIndexes
skippedChunks
```

### 4.2 items 数组

每项必须包含：

| 字段 | 类型 | 要求 |
|---|---|---|
| `question` | string | 非空 |
| `answer` | string | 非空 |
| `quote` | string | 非空，且必须来自 Chunk |
| `pageNo` | integer | 大于等于 1 |
| `chunkIndex` | integer | 当前批次中存在的非负索引 |

### 4.3 覆盖契约

当前批次所有 Chunk 必须被划分到：

```text
coveredChunkIndexes
或
skippedChunks
```

且满足：

1. 两个集合不重叠；
2. 不能有重复 index；
3. 不能出现当前批次之外的 index；
4. 两个集合合并后必须覆盖当前批次全部 index；
5. `items` 中实际出现的 Chunk index 必须与 `coveredChunkIndexes` 一致。

## 5. 修复方法

### 5.1 确认使用最新 Ollama 适配器

检查：

```text
server/app/integrations/model_providers/ollama.py
```

确认 QA 请求包含：

```python
payload["format"] = _QA_SPLIT_OUTPUT_SCHEMA
```

并重启：

```text
Celery QA Worker
```

如果是多 Worker 部署，所有消费 `qa` 队列的 Worker 都必须更新。

### 5.2 缩小 QA Split 批次

建议先将：

```text
QA_SPLIT_MAX_BATCH_CHARS=3000
```

如果仍不稳定，再降到：

```text
QA_SPLIT_MAX_BATCH_CHARS=2000
```

同时将并发降为：

```text
QA_SPLIT_MAX_CONCURRENCY=1
```

这样可以降低模型上下文、输出数量和本地推理资源竞争。

### 5.3 检查 maxTokens

QA Split 输出包含多个数组和每条 QA 的完整字段。如果 `max_tokens` 太小，可能在中途截断。应根据：

```text
预计 QA 数量 × 每条 QA 的平均输出长度
```

设置足够的 `maxTokens`，并预留 `coveredChunkIndexes`、`skippedChunks` 和 JSON 结构的长度。

### 5.4 保持低温度

当前 Ollama QA Split 适配器默认：

```text
temperature = 0
```

不建议 QA Split 使用较高温度，因为它会增加结构漂移、字段缺失和来源索引错误的概率。

### 5.5 对 OpenAI 兼容 Provider 使用更强 Schema

当前 OpenAI 兼容适配器使用：

```json
{
  "response_format": {
    "type": "json_object"
  }
}
```

这主要保证 JSON object，不一定强制完整的 QA Schema。后续可根据供应商支持情况使用 `json_schema`，并传入与 Ollama 相同的字段约束。

不能假设所有 OpenAI 兼容供应商都支持同一种 `json_schema` 参数，应由 Provider 类型或模型配置控制。

### 5.6 将“结构错误”和“可重试错误”分开

当前 `items` 类型错误被标记为：

```text
retryable = false
```

原因是同一 Prompt、同一模型和同一批次重复调用，通常不会自动修复稳定的 Schema 问题。正确处理方式是：

1. 修正 Schema、Prompt、模型参数或批次大小；
2. 重启使用旧代码的 Worker；
3. 重新执行 QA Split。

如果后续要对偶发格式错误重试，应使用“最多一次结构修复重试”，不能无限自动重试。

## 6. 失败任务恢复

该错误发生在 QA Split 阶段，因此：

```text
Document.status = FAILED
ImportJob.stage = QA_SPLITTING
ImportJob.error_code = QA_PROVENANCE_CONTRACT_INVALID
TaskRun.error.retryable = false
```

恢复步骤：

1. 修正 QA ModelConfig 或 Provider；
2. 确认默认模型和 Provider 都是 `ACTIVE`；
3. 重启 QA Worker；
4. 重新执行 `QA_SPLITTING` 阶段；
5. QA Split 成功后再进入 `EMBEDDING`。

不建议直接修改数据库中的 `QaPair` 或绕过 provenance 校验，因为后续 Embedding 和检索依赖 `chunk_id`、`quote`、`page_no` 和 `sourceChunkIndex` 的一致性。

## 7. 如何验收修复

### 7.1 Provider 层

使用指定 `modelConfigId` 做模型连接测试，确认：

```text
providerType = OLLAMA
modelName = gemma3
endpoint = http://localhost:11434/api/chat
```

### 7.2 QA 输出层

模型返回必须满足：

```json
{
  "items": [],
  "coveredChunkIndexes": [],
  "skippedChunks": []
}
```

实际有内容时，`items` 必须是数组，数组元素必须包含完整字段。

### 7.3 数据层

QA Split 成功后检查：

```text
ImportJob.stage = EMBEDDING
Document.status = EMBEDDING
QaPair.status = ACTIVE
QaPair.question_embedding = NULL
QaPair.chunk_id != NULL
```

### 7.4 日志层

检查：

```text
ModelCallLog.status = SUCCESS
ModelCallLog.capability = QA_SPLIT
TaskRun.status = SUCCESS
```

并确保没有新的：

```text
QA_PROVENANCE_CONTRACT_INVALID
```

## 8. 测试覆盖

相关测试文件：

```text
server/tests/test_qa_split_task.py
```

应覆盖：

- `items` 缺失；
- `items` 为 object；
- `items` 为 string；
- `items` 为 null；
- `items` 为空数组；
- item 不是 object；
- 缺少 question、answer、quote；
- pageNo 不合法；
- chunkIndex 不合法；
- covered/skipped 覆盖不完整；
- quote 与源 Chunk 不匹配。

`items` 类型错误与空数组错误不是同一个错误：

| 场景 | 错误 |
|---|---|
| `items` 是 object/string/null | `QA_PROVENANCE_CONTRACT_INVALID`，items 必须是数组 |
| `items` 是空数组且没有有效 Chunk 关联 | `QA_PROVENANCE_CONTRACT_INVALID`，items 为空 |
| JSON 语法损坏 | `QA_SPLIT_INVALID_OUTPUT` |
| JSON 没有覆盖契约 | `QA_PROVENANCE_COVERAGE_MISMATCH` |

