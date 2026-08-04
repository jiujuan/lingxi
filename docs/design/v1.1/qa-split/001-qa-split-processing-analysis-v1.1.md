# QA Split 解析程序步骤分析

> 文档编号：001
> 版本：v1.1
> 分析日期：2026-08-04
> 分析范围：文档导入流水线中的 QA Split 阶段，以及与其直接相邻的 Chunk 生成、Embedding 入队和 QA 查询接口。
> 结论：当前代码把“知识切片后的 QA 文档生成”实现为一个 `QA_SPLITTING` 阶段；该阶段内部已经包含批处理、模型生成、来源校验和 QA 对落库等多个子步骤，但后端没有单独的“知识切片”或“QA 文档生成”状态值。

## 1. 分析目标与结论

本文件用于回答以下问题：

1. QA Split 解析程序从哪里进入，经过哪些程序步骤；
2. 每个步骤的输入、处理逻辑、输出和状态变化；
3. QA Split 与前置文档解析/知识切片、后置向量化/知识入库的边界；
4. 每个步骤涉及的文件、类、函数和测试；
5. 失败、重试、幂等、来源追溯和事务一致性如何实现；
6. 如果页面需要把原来的 4 个显示步骤拆成 6 个步骤，现有后端代码能够直接支撑哪些显示状态，哪些状态仍需要新增后端阶段或只做前端语义映射。

核心结论如下：

- `DocumentParseService.parse_import_job()` 负责读取文件、调用解析器和生成 `DocumentChunk`；它完成后把任务切换到 `QA_SPLITTING`。
- `parse_document_task` 将已经完成 Chunk 生成的任务发送到 `qa` 队列。
- `split_document_qa_task` 是 QA Split 的 Celery 入口，实际业务由 `QaSplitService.split_import_job_for_task()` 执行。
- `QaSplitService` 先读取当前有效的 Child Chunk，再按字符预算分批，调用租户默认的 `QA_SPLIT` 模型，校验返回 JSON 的来源关系，最后替换当前文档的 QA 对。
- QA Split 成功后，任务只完成“QA 对生成”这部分工作，状态被推进到 `EMBEDDING`，随后由 `embed_qa_pairs_task` 完成向量化、知识入库和最终 `READY`/`COMPLETED`。
- 当前“知识切片”实际发生在 `DocumentParseService` 的解析后处理阶段，而不是 `QaSplitService` 内部。`QaSplitService` 消费已有 Chunk，不重新切分原文。
- 当前后端没有独立的 `KNOWLEDGE_SLICING`、`QA_GENERATION`、`VECTORIZATION`、`KNOWLEDGE_INDEXING` 阶段常量。若页面只需要 6 个视觉步骤，可以通过前端将真实阶段映射为更细的展示进度；若要求任务接口和数据库也能查询 6 个独立阶段，则需要另行修改状态机、进度写入、任务日志和重试恢复逻辑。

## 2. 当前流水线位置

### 2.1 当前真实执行链路

```mermaid
flowchart LR
    A["上传文件并创建 ImportJob"] --> B["parse_document_task<br/>parse 队列"]
    B --> C["DocumentParseService<br/>解析文件"]
    C --> D["生成 Parsed Markdown 和 DocumentChunk"]
    D --> E["任务 stage=QA_SPLITTING"]
    E --> F["enqueue_qa_task<br/>qa 队列"]
    F --> G["split_document_qa_task"]
    G --> H["QaSplitService<br/>生成并校验 QA 对"]
    H --> I["写入 qa_pairs<br/>stage=EMBEDDING"]
    I --> J["enqueue_embedding_task<br/>embedding 队列"]
    J --> K["embed_qa_pairs_task"]
    K --> L["QA/Chunk 向量化"]
    L --> M["INDEXING 阶段写入并完成事务"]
    M --> N["Document=READY<br/>ImportJob=COMPLETED"]
```

### 2.2 与页面 4 步/6 步显示的对应关系

当前代码中可以确认的后端阶段如下：

| 当前后端阶段 | 主要代码位置 | 实际含义 |
|---|---|---|
| `PARSING` | `server/app/services/document_parse_service.py` | 读取文件并调用解析器 |
| `CHUNKING` | `server/app/services/document_parse_service.py` | 将解析结果写成 Chunk；自适应模式下生成 Parent/Child |
| `QA_SPLITTING` | `server/app/services/qa_split_service.py` | 读取 Child Chunk，生成和校验 QA 对 |
| `EMBEDDING` | `server/app/services/embedding_service.py` | 读取 QA 对并调用 Embedding 模型 |
| `INDEXING` | `server/app/services/embedding_service.py` | 写入 QA/Chunk 向量、搜索文本和元数据 |
| `COMPLETED` | `server/app/services/embedding_service.py` | 文档达到 `READY`，导入任务完成 |

因此，用户所要求的 6 个页面步骤可以按下表理解：

| 页面显示步骤 | 推荐对应的真实代码范围 | 当前是否有独立后端状态 |
|---|---|---|
| 1. 文档解析 | `DocumentParseService` 调用 parser | 有，`PARSING` |
| 2. 知识切片 | `DocumentParseService._write_legacy_chunks()` 或 `_write_adaptive_chunks()` | 没有独立状态；当前与解析任务同属 parse worker，短暂写入 `CHUNKING` |
| 3. QA 文档生成 | `QaSplitService._generate_qa_items()`、`_replace_qa_pairs()` | 没有独立状态；当前统一显示为 `QA_SPLITTING` |
| 4. 向量化 | `EmbeddingService._embed_targets()`、`_embed_in_batches()` | 没有独立页面状态；当前统一显示为 `EMBEDDING` |
| 5. 知识入库 | `EmbeddingService._persist_targets()`，随后提交 `READY` | 没有独立状态；当前在 `INDEXING` 内完成 |
| 6. 完成上架和可检索使用 | `DocumentStatus.READY`、`ImportJobStatus.COMPLETED` | 有，`COMPLETED`/`READY` |

注意：当前 `DocumentParseService` 在解析成功后先写 `CHUNKING` 并提交，再把任务切换到 `QA_SPLITTING` 并提交；所以“知识切片”在后端内部确实有一个短暂的 `CHUNKING` 值，但 `ImportService.job_to_dict()` 和页面目前通常只把它作为任务阶段数据返回，不代表已经形成了面向用户的独立 6 步状态机。

## 3. 文件和程序入口总览

### 3.1 主链路文件

| 文件 | 主要类/函数 | 作用 |
|---|---|---|
| `server/app/tasks/parse_tasks.py` | `parse_document_task()` | 解析任务完成后，将 `QA_SPLITTING` 任务放入 `qa` 队列 |
| `server/app/tasks/qa_tasks.py` | `split_document_qa_task()` | QA Split Celery 入口，处理任务结果、重试和 Embedding 入队 |
| `server/app/services/qa_split_service.py` | `QaSplitService` | QA Split 业务主流程、模型调用、校验、QA 对落库、失败记录 |
| `server/app/services/qa_prompt_builder.py` | `build_qa_split_prompt()` | 构造传给 QA 模型的提示词 |
| `server/app/services/_batching.py` | `run_ordered()` | 并发调用外部模型，同时保持批次结果顺序 |
| `server/app/services/import_service.py` | `enqueue_qa_task()`、`enqueue_embedding_task()` | 跨队列投递 Celery 任务 |
| `server/app/tasks/_common.py` | `resolve_task_outcome()`、`handle_failure()` | 根据持久化错误决定重试或终止 |
| `server/app/services/embedding_service.py` | `EmbeddingService.embed_import_job()` | QA Split 成功后的向量化和最终入库 |

### 3.2 配置、模型和接口文件

| 文件 | 关键内容 |
|---|---|
| `server/app/core/config.py` | `QA_STRICT_PROVENANCE_ENABLED`、`QA_SPLIT_MAX_BATCH_CHARS`、`QA_SPLIT_MAX_CONCURRENCY` |
| `server/app/core/service_factory.py` | 将 Settings 中的来源校验开关注入 `QaSplitService` |
| `server/app/integrations/model_providers/base.py` | `ChatProvider.generate_qa_pairs()`、`ProviderError` |
| `server/app/integrations/model_providers/registry.py` | 按供应商类型构建真实适配器或 `MockProvider` |
| `server/app/integrations/model_providers/openai_compatible.py` | OpenAI 兼容接口 QA JSON 调用 |
| `server/app/integrations/model_providers/ollama.py` | Ollama 原生 JSON 调用 |
| `server/app/integrations/model_providers/claude.py` | Claude 消息接口调用；QA 复用 `complete_chat()` |
| `server/app/models/import_job.py` | `ImportJob.status`、`stage`、`progress`、错误字段和 `options` |
| `server/app/models/document.py` | `DocumentStatus` 和文档处理状态字段 |
| `server/app/models/qa_pair.py` | `DocumentChunk`、`QaPair` 数据结构 |
| `server/app/models/logs.py` | `TaskRun` 任务执行记录 |
| `server/app/api/v1/documents.py` | QA 对查询和 QA 重新生成接口 |
| `server/app/repositories/qa_pair_repo.py` | QA 对分页查询 |

## 4. QA Split 主流程详细步骤

以下步骤按实际调用顺序排列。第 1、2 步是 QA Split 的任务边界；第 3 至第 12 步是核心 QA Split 处理；第 13、14 步是进入下游 Embedding 的衔接。

### 步骤 1：解析任务完成后进入 QA 队列

**入口文件和函数**

- `server/app/tasks/parse_tasks.py:11`，`parse_document_task()`
- `server/app/services/import_service.py:50`，`enqueue_qa_task()`

**处理逻辑**

1. `parse_document_task()` 调用 `DocumentParseService.parse_import_job(job_id)`。
2. 文档解析服务完成 Markdown 和 Chunk 落库后，将：
   - `job.stage` 设置为 `QA_SPLITTING`；
   - `job.progress` 设置为 `40`；
   - `document.status` 设置为 `DocumentStatus.QA_SPLITTING`。
3. 解析任务返回后，`parse_document_task()` 判断：

   ```python
   if job.stage == "QA_SPLITTING" and job.status == "RUNNING":
       enqueue_qa_task(job.id)
   ```

4. `enqueue_qa_task()` 通过 `split_document_qa_task.apply_async(..., queue="qa")` 投递到 QA 队列。

**输入**

- 已绑定文件的 `ImportJob`；
- 解析器输出的 Markdown；
- `DocumentChunk` 集合，至少包含可检索的 Child Chunk。

**输出**

- 一个进入 `qa` 队列的 Celery 消息；
- 消息参数为 `job_id`，可选参数 `enqueue_embedding` 默认值为 `True`。

**异常**

- Broker 入队失败不会被静默吞掉；
- `enqueue_qa_task()` 记录安全日志后重新抛出异常；
- 解析 Worker/Celery 层据此执行任务重试；
- 同步 API 场景下，`ImportService._enqueue_or_mark_failed()` 会将任务标记为 `TASK_ENQUEUE_FAILED`。

**边界说明**

这一步不是 QA 模型处理。它只负责把前置解析和知识切片的结果交给 QA Split worker。

### 步骤 2：QA Worker 建立任务上下文并执行幂等判断

**入口文件和函数**

- `server/app/tasks/qa_tasks.py:9-42`，`split_document_qa_task()`
- `server/app/core/service_factory.py:104-112`，`build_qa_split_service()`
- `server/app/services/qa_split_service.py:492-503`，`split_import_job_for_task()`

**处理逻辑**

1. Celery worker 使用 `SessionLocal()` 创建数据库会话。
2. 通过 `build_qa_split_service(session)` 创建 `QaSplitService`。
3. Service 根据 `QA_STRICT_PROVENANCE_ENABLED` 注入旧数据兼容策略：
   - 严格来源校验开启时，`legacy_missing_chunk_index_compatibility=False`；
   - 严格来源校验关闭时，允许对缺少 `chunkIndex` 的旧模型输出做唯一匹配兼容。
4. Service 查询 `ImportJob` 和关联 `Document`。
5. 如果 `job.status == COMPLETED`，直接返回，避免重复生成 QA 对或重复创建 `TaskRun`。

**输出**

- 成功或失败的 `ImportJob`；
- 当前调用创建的 `TaskRun.id`；
- 对已完成任务，返回的 `task_run_id` 为 `None`。

**幂等意义**

- Celery 使用 `acks_late=True`，任务可能因 worker 崩溃而重复投递；
- `ImportJobStatus.COMPLETED` 是最终幂等保护；
- QA Split 成功但尚未完成 Embedding 时，任务仍为 `RUNNING`，再次投递会进入服务流程，后续需要依靠数据绑定和下游逻辑继续处理。

### 步骤 3：创建 QA TaskRun，切换到 QA_SPLITTING

**代码位置**

- `server/app/services/qa_split_service.py:505-523`
- `server/app/models/logs.py:7-22`
- `server/app/models/document.py:7-16`
- `server/app/models/import_job.py:8-26`

**处理逻辑**

Service 为本次调用创建：

```text
task_type    = split_document_qa_task
queue_name   = qa
resource_type= IMPORT_JOB
resource_id  = job.id
stage        = QA_SPLITTING
status       = RUNNING
```

随后写入任务和文档状态：

| 对象 | 字段 | 值 |
|---|---|---|
| `ImportJob` | `status` | `RUNNING` |
| `ImportJob` | `stage` | `QA_SPLITTING` |
| `ImportJob` | `progress` | `max(当前进度, 45)` |
| `Document` | `status` | `QA_SPLITTING` |
| `TaskRun` | `stage` | `QA_SPLITTING` |
| `TaskRun` | `status` | `RUNNING` |

**设计目的**

- 让任务中心能知道当前处于 QA 处理；
- 把失败码、失败消息和 `retryable` 记录在 `TaskRun.error`；
- 使用 `45` 作为 QA Split 阶段的最小进度，避免重试或重复投递时进度倒退。

**事务特点**

此处使用 `flush()` 获取 `TaskRun.id`，但在外部模型调用前没有单独提交。QA Split 成功或失败时由后面的统一 `commit()` 完成持久化。

### 步骤 4：选择当前有效的 Child Chunk

**代码位置**

- `server/app/services/qa_split_service.py:764-791`
- `server/app/models/qa_pair.py:12-104`

**函数**

```text
QaSplitService._list_chunks(document_id)
```

**查询条件**

只选择满足以下条件的 `DocumentChunk`：

- `document_id` 等于当前文档；
- `deleted_at IS NULL`；
- `status == "ACTIVE"`；
- `chunk_level == "CHILD"`。

**为什么只消费 Child Chunk**

- 自适应层级切片会在同一张表中同时保存 Parent 和 Child；
- Parent 用于上下文组织，不应直接作为最终 QA 生成的可检索细粒度来源；
- QA 对需要能回溯到真实可检索片段，所以只消费 Child。

**Chunk 代际选择**

1. 按 `created_at DESC, id DESC` 找到最新的有效 Child；
2. 取最新 Child 的 `chunker_config_hash`；
3. 只保留相同配置哈希的 Child；
4. 按 `chunk_index` 升序返回。

这样可以避免不同 Chunk generation 混在同一个 QA 批次中，造成：

- 重复的 `chunkIndex`；
- QA 对引用旧代 Chunk；
- 后续 Embedding 绑定到无法唯一确定的来源集合。

**无 Chunk 处理**

如果没有有效 Child Chunk，抛出：

```text
QA_PROVENANCE_NO_SPLITTABLE_CHUNKS
文档没有可拆分的 Chunk
retryable = false
```

该错误通常说明前置解析、Chunk 生成或数据状态不满足 QA 前置条件，重试同一数据不会自动解决。

### 步骤 5：选择租户默认 QA Split 模型

**代码位置**

- `server/app/services/qa_split_service.py:645-669`
- `server/app/models/model_config.py`
- `server/app/core/secrets.py`

**函数**

```text
QaSplitService._default_model(tenant_id)
```

**查询条件**

通过 `ModelConfig` 联查 `ModelProvider`，要求：

- `ModelConfig.tenant_id == tenant_id`；
- `ModelConfig.capability == "QA_SPLIT"`；
- `ModelConfig.is_default == True`；
- 模型状态为 `ACTIVE`；
- 模型未软删除；
- Provider 状态为 `ACTIVE`；
- Provider 未软删除。

**返回**

```text
(ModelConfig, ModelProvider)
```

**Provider 配置组装**

`split_import_job_for_task()` 随后完成以下操作：

1. 从 `provider.encrypted_api_key` 解密 API Key；
2. 合并 Provider 级 `config` 和 Model 级 `config`；
3. 传入 `provider_type`、`base_url`、模型名称和超时时间；
4. 调用 `build_provider_adapter()` 构造具体适配器。

**错误**

未找到默认模型时抛出：

```text
QA_SPLIT_MODEL_NOT_CONFIGURED
未配置默认 QA Split 模型
retryable = false
```

原因是模型配置缺失不是临时网络故障，自动重试不能解决。

### 步骤 6：构造 Provider 适配器

**代码位置**

- `server/app/integrations/model_providers/registry.py:25-83`
- `server/app/integrations/model_providers/base.py:18-47`
- `server/app/services/qa_split_service.py:533-541`

**适配器选择逻辑**

`build_provider_adapter()` 首先合并模型名称、超时时间和配置。如果出现以下任一情况，则使用本地 `MockProvider`：

- `base_url` 为空；
- `base_url` 以 `mock://` 开头；
- 配置中 `mock == true`；
- 配置包含 `qaSplitResponse`、`chatResponse`、`chatError` 或 `testMode` 等测试标记。

否则按 `provider_type` 选择：

| Provider 类型 | 适配器 | QA 调用方式 |
|---|---|---|
| `OPENAI_COMPATIBLE` | `OpenAICompatibleProvider` | Chat Completions，设置 `response_format={"type":"json_object"}` |
| `OLLAMA` | `OllamaProvider` | `/api/chat`，设置 `format="json"` |
| `CLAUDE` | `ClaudeProvider` | Messages API，QA 复用 `complete_chat()` |
| `INTERNAL_GATEWAY` | `InternalGatewayProvider` | 内部网关的 OpenAI 兼容调用 |
| Mock | `MockProvider` | 返回配置的固定 JSON 或测试默认 JSON |

**统一错误**

真实 HTTP Provider 通过 `ProviderError` 统一传递：

- 错误码；
- 用户可见错误消息；
- HTTP 状态码；
- `retryable`。

网络超时、网络传输失败、429、5xx 等通常可重试；认证失败、请求格式错误等通常不可重试。

### 步骤 7：按照字符预算对 Chunk 分组

**代码位置**

- `server/app/services/qa_split_service.py:671-702`
- `server/app/core/config.py:393-398`
- `server/tests/test_batching_pipeline.py:88-164`

**函数**

```text
QaSplitService._group_chunks(chunks)
```

**默认配置**

| 配置项 | 环境变量 | 默认值 | 作用 |
|---|---|---:|---|
| `qa_split_max_batch_chars` | `QA_SPLIT_MAX_BATCH_CHARS` | `6000` | 单个 QA Prompt 的近似字符预算 |
| `qa_split_max_concurrency` | `QA_SPLIT_MAX_CONCURRENCY` | `4` | 并发调用模型的最大批次数 |

**分组算法**

使用贪心策略遍历已经按 `chunk_index` 排序的 Chunk：

1. 计算 `len(chunk.content or "")`；
2. 当前批次为空，或者加上当前 Chunk 后未超过预算，则继续放入当前批次；
3. 如果会超预算，先提交当前批次，再新建批次；
4. 普通旧版 Chunk 即使自身超过预算，也会单独形成一个批次；
5. `adaptive_hierarchical` Chunk 如果自身超过预算，直接失败，不发送模型请求。

**重要特点**

- 预算只按 Chunk 正文字符数估算，不是严格 Token 计数；
- 目前没有把文档标题、标题路径、页码标记的额外字符显式计入预算；
- 分组不会改变 Chunk 的 `chunk_index`；
- 组内顺序和组顺序都会保留。

**自适应 Chunk 超预算错误**

```text
QA_PROVENANCE_CONTRACT_INVALID
Adaptive Chunk 超出 QA batch 字符预算
retryable = false
```

该保护用于避免自适应切片生成了无法放入 QA 模型上下文的单个 Child。

### 步骤 8：为每个批次构造 QA Prompt

**代码位置**

- `server/app/services/qa_prompt_builder.py:1-35`
- `server/tests/test_qa_split_task.py:409-426`

**函数**

```text
build_qa_split_prompt(document, chunks)
```

**Prompt 内容**

Prompt 依次包含：

1. 角色说明：企业知识库 QA 拆分助手；
2. 任务说明：基于原文生成可检索的问题、答案、引用和页码；
3. 严格 JSON 输出格式；
4. `question`、`answer`、`quote`、`pageNo`、`chunkIndex` 字段要求；
5. `coveredChunkIndexes` 和 `skippedChunks` 覆盖契约；
6. 文档标题；
7. 每个 Chunk 的：
   - `chunkIndex`；
   - `pageRange`；
   - `title`/标题路径；
   - 原文内容。

**模型输出契约**

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
  "skippedChunks": [
    {
      "chunkIndex": 1,
      "reason": "该片段没有足够信息生成独立问题"
    }
  ]
}
```

**覆盖契约的意义**

- `coveredChunkIndexes` 表示至少生成了一条 QA 的来源 Chunk；
- `skippedChunks` 明确记录没有生成 QA 的 Chunk 及原因；
- 两者必须对当前批次的全部 `chunkIndex` 构成不重复、不重叠、不缺失的分区；
- `items` 中出现的 Chunk 集合必须与 `coveredChunkIndexes` 一致。

这个契约避免模型只处理批次中的部分内容，却被系统误判为整个批次成功。

### 步骤 9：并发调用 QA 模型并保持结果顺序

**代码位置**

- `server/app/services/qa_split_service.py:704-737`
- `server/app/services/_batching.py:16-42`

**函数**

```text
QaSplitService._generate_qa_items(adapter, document, groups)
```

**调用顺序**

1. 为每一个 Chunk group 构造 Prompt；
2. 调用 `adapter.generate_qa_pairs(prompt)`；
3. 使用 `run_ordered(groups, generate, qa_split_max_concurrency)`；
4. 得到与输入 `groups` 顺序一致的原始模型输出；
5. 逐组调用 `validate_qa_split_output()`；
6. 依次合并每组的 `ValidatedQaItem`。

**并发模型**

- `run_ordered()` 使用 `ThreadPoolExecutor`；
- 并发上限为 `min(配置上限, 批次数)`；
- `max_workers <= 1` 或只有一个批次时串行执行；
- 线程池只执行不触碰数据库 Session 的外部模型调用；
- 数据库写入和结果合并在主线程完成；
- `executor.map()` 保证结果顺序与输入顺序一致。

**异常传播**

- 任意模型调用抛出 `ProviderError`，向上交给 `split_import_job_for_task()`；
- 任意批次校验失败，停止后续落库；
- 只有全部批次调用并校验完成，才会进入 QA 对替换步骤。

**一致性保证**

即使第一批成功、后续批次失败，第一批的 QA 结果也不会提前写入数据库，因为 QA 对替换只发生在所有批次验证结束之后。

### 步骤 10：解析和校验模型返回的 JSON

**代码位置**

- `server/app/services/qa_split_service.py:78-108`
- `server/app/services/qa_split_service.py:114-120`
- `server/app/services/qa_split_service.py:197-244`
- `server/app/services/qa_split_service.py:266-339`
- `server/app/services/qa_split_service.py:342-469`

**入口函数**

```text
validate_qa_split_output(
    raw_output,
    chunks,
    allow_legacy_missing_chunk_index=...
)
```

#### 10.1 提取 JSON

`_extract_json_text()` 支持：

- 纯 JSON；
- 外层 Markdown code fence；
- JSON 前后带说明文字；
- 从第一处 `{`/`[` 到最后一个 `}`/`]` 截取常见包装内容。

如果最终不能通过 `json.loads()` 解析，返回：

```text
QA_SPLIT_INVALID_OUTPUT
retryable = false
```

#### 10.2 校验顶层结构

要求：

- 顶层必须是 JSON object；
- `items` 必须是数组；
- 有传入 `chunks` 时，当前批次不能为空；
- 当前批次的 `chunkIndex` 不能重复。

#### 10.3 校验每个 QA 项

`_validate_item_fields()` 要求：

| 字段 | 要求 |
|---|---|
| `question` | 非空字符串 |
| `answer` | 非空字符串 |
| `quote` | 非空字符串 |
| `pageNo` | 正整数；兼容 `page_no` |
| `chunkIndex` | 非负整数；兼容 `chunk_index` |

代码会对 `question` 和 `answer` 做 `strip()`；原始 `quote` 仍保留，用于后续持久化。

#### 10.4 校验 Chunk 来源

对于每个 QA 项：

1. `chunkIndex` 必须属于当前批次；
2. `pageNo` 必须处于对应 Chunk 的 `[page_start, page_end]`；
3. 如果没有 `page_start/page_end`，则回退到 `page_no`；
4. 如果页码也为空，则默认页码范围为第 1 页；
5. `quote` 必须是目标 Chunk 内容的子串；
6. 比较引用时使用 Unicode NFC 归一化和连续空白折叠；
7. 入库时仍保存模型原始 `quote`，不会保存归一化后的值。

可能的错误码：

```text
QA_PROVENANCE_UNKNOWN_CHUNK_INDEX
QA_PROVENANCE_QUOTE_MISMATCH
QA_PROVENANCE_CONTRACT_INVALID
```

#### 10.5 校验覆盖完整性

如果输出带有 `coveredChunkIndexes` 或 `skippedChunks` 任意一个字段，则按严格覆盖契约处理：

- 两个字段都必须存在且为数组；
- `coveredChunkIndexes` 不得重复；
- `skippedChunks` 每项必须有合法 `chunkIndex` 和非空 `reason`；
- 两个集合都不能引用当前批次之外的 Chunk；
- 两个集合不能重叠；
- 两个集合的并集必须恰好等于当前批次的全部 Chunk；
- `items` 中出现的 Chunk 集合必须等于 `coveredChunkIndexes`。

如果严格覆盖不成立，返回：

```text
QA_PROVENANCE_COVERAGE_MISMATCH
```

#### 10.6 旧数据兼容

`ServiceDependencies.build_qa_split_service()` 将严格来源开关转换为构造参数：

```text
QA_STRICT_PROVENANCE_ENABLED = true
    -> 不允许缺少 chunkIndex

QA_STRICT_PROVENANCE_ENABLED = false
    -> 允许旧输出通过 pageNo + quote 唯一匹配 Chunk
```

兼容匹配由 `_resolve_legacy_chunk_index()` 完成，必须满足：

- 页码落在 Chunk 页码范围内；
- 归一化后的 quote 属于 Chunk 内容；
- 匹配结果必须唯一。

不能唯一匹配时不会默认取第一个 Chunk，而是失败并返回 `QA_PROVENANCE_MISSING_CHUNK_INDEX`。

### 步骤 11：替换当前文档的 QA 对

**代码位置**

- `server/app/services/qa_split_service.py:793-832`
- `server/app/models/qa_pair.py:113-141`

**函数**

```text
QaSplitService._replace_qa_pairs(job, document, chunks, items)
```

**处理逻辑**

1. 创建 `chunk_index -> DocumentChunk` 映射；
2. 将每个 `ValidatedQaItem` 解析到真实 `DocumentChunk`；
3. 如果某个 QA 项无法关联 Chunk，则失败；
4. 删除当前文档已有的全部 `QaPair`；
5. 按合并后的结果顺序创建新的 `QaPair`。

**写入字段**

| `QaPair` 字段 | 来源 |
|---|---|
| `tenant_id` | 当前导入任务租户 |
| `document_id` | 当前文档 |
| `chunk_id` | QA 项的 `chunkIndex` 对应 Child Chunk |
| `job_id` | 当前 ImportJob |
| `pair_index` | 合并结果中的顺序 |
| `question` | 模型输出 |
| `answer` | 模型输出 |
| `quote` | 模型输出原始引用 |
| `page_no` | 模型输出 `pageNo` |
| `question_embedding` | 初始为 `None`，等待 Embedding |
| `search_text` | 初始为空字符串，等待 Embedding 阶段重建 |
| `token_count` | 当前实现按 question 和 answer 的 `split()` 长度估算 |
| `status` | `ACTIVE` |
| `qa_metadata` | 保存 `sourceChunkIndex` |

**重要语义**

- QA Split 负责生成结构化 QA 对，不负责生成问题向量；
- `question_embedding=None` 表示 QA 对还不能独立完成向量检索；
- `chunk_id`、`quote`、`page_no` 和 `sourceChunkIndex` 共同保留来源追溯链；
- 重新生成 QA 时会删除旧 QA 对并重建当前文档的集合。

**事务边界**

此函数使用当前 SQLAlchemy Session 执行删除和新增，但不单独提交。最终由主流程成功提交，或者由失败处理提交。

### 步骤 12：绑定 Embedding 使用的 Chunk generation

**代码位置**

- `server/app/services/qa_split_service.py:739-762`
- `server/app/services/embedding_service.py:225-240`

**函数**

```text
QaSplitService._bind_embedding_run_config_hash(job, chunks)
```

**处理逻辑**

1. 收集所有来源 Chunk 的 `chunker_config_hash`；
2. 删除空值；
3. 要求集合中必须恰好只有一个配置哈希；
4. 将该值写入：

```json
{
  "embedding": {
    "run_config_hash": "..."
  }
}
```

5. 通过重新赋值整个 `job.options`，确保 SQLAlchemy 对 JSON 嵌套结构的变更可持久化。

**目的**

Embedding 阶段需要知道 QA 对来自哪一代 Child Chunk。它会依据这个哈希只读取仍然有效且属于同一 generation 的 QA 对和 Child Chunk。

**失败情况**

如果 Chunk 来源配置无法唯一确定，抛出：

```text
QA_SPLIT_RUN_CONFIG_INVALID
QA 来源 Chunk generation 无法唯一确定
```

这项检查阻止“QA 对来自混合 generation，但 Embedding 阶段无法判断应该给哪一代数据建立索引”的情况。

### 步骤 13：记录 QA Split 可观测性数据

**代码位置**

- `server/app/services/qa_split_service.py:114-159`
- `server/app/core/metrics.py`

**函数**

```text
log_qa_split_observability(...)
```

**记录内容**

- 租户 ID；
- 文档 ID；
- 导入任务 ID；
- Chunk generation 配置哈希；
- 来源 Chunk 数；
- 被 QA 覆盖的 Chunk 数；
- QA 对数量；
- 覆盖率 `coverage_ratio`。

**数据保护**

日志和指标不写入 Prompt、QA 答案、原文内容或 quote，避免把业务知识内容直接写入运行日志。

**指标意义**

覆盖率可以识别：

- 大量 Chunk 被跳过；
- 模型只生成少量 QA；
- 某一类文档的 QA 生成质量下降；
- Chunk generation 切换后 QA 覆盖异常。

### 步骤 14：QA Split 成功提交并切换到 Embedding

**代码位置**

- `server/app/services/qa_split_service.py:554-566`

**成功状态变化**

| 对象 | 字段 | 成功值 |
|---|---|---|
| `Document` | `qa_pair_count` | 本次生成的 QA 数 |
| `Document` | `status` | `EMBEDDING` |
| `Document` | 错误字段 | 清空 |
| `ImportJob` | `stage` | `EMBEDDING` |
| `ImportJob` | `progress` | `65` |
| `ImportJob` | `status` | `RUNNING` |
| `ImportJob` | 错误字段 | 清空 |
| `TaskRun` | `status` | `SUCCESS` |
| `TaskRun` | `error` | `None` |

最后提交事务并返回 `(job, task_run.id)`。

**为什么不是 `COMPLETED`**

QA 对虽然已落库，但：

- 问题还没有 Embedding 向量；
- QA `search_text` 还没有在最终向量化阶段构建；
- 自适应模式下 Child Chunk 向量还没有写入；
- 文档还不能被完整的向量检索和混合检索使用。

所以 QA Split 成功只意味着“QA 文档生成完成”，不代表“知识已上架”。

### 步骤 15：QA Worker 投递 Embedding 任务

**代码位置**

- `server/app/tasks/qa_tasks.py:24-40`
- `server/app/services/import_service.py:64-72`
- `server/app/tasks/embedding_tasks.py:9-31`

**处理逻辑**

1. `split_document_qa_task()` 调用 `resolve_task_outcome()`；
2. 如果 QA Split 失败，根据 `TaskRun.error.retryable` 交给 `handle_failure()`；
3. 如果：

   ```text
   enqueue_embedding == true
   job.stage == EMBEDDING
   job.status == RUNNING
   ```

   则调用 `enqueue_embedding_task(job.id)`；
4. `enqueue_embedding_task()` 将 `embed_qa_pairs_task` 投递到 `embedding` 队列；
5. Embedding Worker 调用 `EmbeddingService.embed_import_job(job_id)`。

**Embedding 入队失败**

如果 QA Split 已成功、但 Broker 投递 Embedding 失败：

1. 调用 `QaSplitService.mark_embedding_enqueue_failed()`；
2. 将当前 Job、Document 和 QA TaskRun 标记为失败；
3. 错误码为 `EMBEDDING_ENQUEUE_FAILED`；
4. `retryable=True`；
5. 由 Celery 的任务重试机制重新处理。

这样不会出现“QA 已完成，但消息丢失，任务永远停留在 EMBEDDING”的静默卡死。

## 5. QA Split 前置的知识切片步骤

用户提出的“知识切片”在现有代码中的主要实现不在 `QaSplitService`，而在文档解析服务。理解这个边界对于拆分页面 6 个步骤非常重要。

### 5.1 解析和切片入口

**文件**

- `server/app/tasks/parse_tasks.py`
- `server/app/services/document_parse_service.py`

**关键函数**

- `DocumentParseService.parse_import_job()`
- `DocumentParseService._replace_parse_outputs()`
- `DocumentParseService._write_legacy_chunks()`
- `DocumentParseService._write_adaptive_chunks()`
- `DocumentParseService._chunk_row()`

### 5.2 解析阶段

`parse_import_job()` 会：

1. 查询 ImportJob；
2. 对 Document 加行锁，串行化同一文档的集合替换；
3. 创建 `parse_document_task` 类型的 `TaskRun`；
4. 设置 `PARSING` 和进度 `20`；
5. 读取 `ImportJobFile`；
6. 从 Object Storage 读取文件；
7. 通过 parser registry 选择解析器；
8. 调用 parser 生成 Markdown 和原子文本块；
9. 文件没有文本块时返回 `PARSER_NO_CONTENT`。

### 5.3 Chunk 写入阶段

解析成功后：

1. 任务阶段短暂切换到 `CHUNKING`；
2. 进度设置为 `30`；
3. 将解析产物写入 `ParseArtifact`；
4. 旧版模式调用 `_write_legacy_chunks()`：
   - 删除当前文档旧 Chunk；
   - 按 parser block 的 index 写入 `DocumentChunk`；
5. 自适应模式调用 `_write_adaptive_chunks()`：
   - 根据 `ChunkPolicy` 生成 Parent/Child；
   - 保存 `chunker_name`、`chunker_version`、`chunker_config_hash`；
   - 先写 STAGING；
   - 完整写入后将旧 ACTIVE 集合设为 SUPERSEDED；
   - 将新集合切换为 ACTIVE；
6. 提交后设置：
   - `Document.status = QA_SPLITTING`；
   - `ImportJob.stage = QA_SPLITTING`；
   - `ImportJob.progress = 40`。

### 5.4 对 6 步页面的含义

如果前端要展示：

1. 文档解析；
2. 知识切片；
3. QA 文档生成；

那么第 1、2 步可以分别绑定解析服务在提交前后的内部状态。但需要注意：

- `PARSING` 和 `CHUNKING` 属于同一个 parse Celery 任务；
- `CHUNKING` 只在解析任务的中间阶段存在；
- 解析任务提交后，页面从后端轮询到的值可能直接是 `QA_SPLITTING`；
- 如果需要稳定地显示“知识切片”步骤，建议新增显式事件/阶段或前端基于进度区间做过渡显示，不能假设轮询一定能捕获瞬时的 `CHUNKING`。

## 6. QA Split 后置的向量化和知识入库步骤

QA Split 成功后，真正让文档可检索的是 `EmbeddingService`。

### 6.1 Embedding 任务入口

**文件**

- `server/app/tasks/embedding_tasks.py`
- `server/app/services/embedding_service.py`

**函数**

- `embed_qa_pairs_task()`
- `EmbeddingService.embed_import_job()`

### 6.2 读取 Embedding 模型和运行配置

Embedding Service：

1. 查询租户默认 `EMBEDDING` 模型；
2. 读取 `job.options.embedding.run_config_hash`；
3. 自适应模式下确认当前 ACTIVE Chunk collection 仍是同一 generation；
4. 读取当前文档的 ACTIVE 或 `EMBEDDING_FAILED` QA 对；
5. 自适应模式下通过 `QaPair.chunk_id` 和 `run_config_hash` 限定来源；
6. 构造 QA 和可选 Child Chunk 的 Embedding targets。

### 6.3 生成向量

QA target 的输入文本是 `qa_pair.question`。同时构建全文检索用 `search_text`，其中包含：

- 文档标题；
- 来源标题路径；
- 问题；
- 答案；
- quote。

如果启用了 Chunk indexing，还会对 Child Chunk 生成：

- 文档标题；
- 标题路径；
- block 类型；
- Chunk 正文。

随后：

1. 按 `EMBEDDING_BATCH_SIZE` 分批；
2. 通过 `run_ordered()` 并发调用 Provider；
3. 对可重试 ProviderError 按 `EMBEDDING_BATCH_MAX_RETRIES` 进行批次内退避；
4. 校验返回向量数量；
5. 校验每个向量的维度。

### 6.4 向量和搜索文本入库

`EmbeddingService._persist_targets()` 写入：

| 目标 | 写入内容 |
|---|---|
| QA 对 | `question_embedding`、`search_text`、`token_count`、Embedding metadata、状态 |
| Child Chunk | `embedding`、`search_text`、Chunk metadata |

完成写入前，任务阶段设置为：

```text
job.stage = INDEXING
job.progress >= 90
task_run.stage = INDEXING
```

最终事务提交时设置：

```text
document.status = READY
job.status = COMPLETED
job.stage = COMPLETED
job.progress = 100
task_run.status = SUCCESS
```

这对应页面第 5 步“知识入库”完成后进入第 6 步“完成上架和可检索使用”。

## 7. 状态、进度和任务日志流转

### 7.1 ImportJob 状态

```text
CREATED
  -> PARSING
  -> CHUNKING
  -> QA_SPLITTING
  -> EMBEDDING
  -> INDEXING
  -> COMPLETED
```

失败时：

```text
任意阶段 -> FAILED
```

其中 `ImportJob.status` 与 `ImportJob.stage` 是两个不同概念：

- `status` 表示任务总体是否仍在运行、完成或失败；
- `stage` 表示当前处理阶段；
- QA Split 成功后，`status` 仍为 `RUNNING`，`stage` 变为 `EMBEDDING`；
- 只有 Embedding/Indexing 成功后，`status` 才变为 `COMPLETED`。

### 7.2 Document 状态

```text
UPLOADED
  -> PARSING
  -> QA_SPLITTING
  -> EMBEDDING
  -> READY
```

任意不可恢复或最终重试失败：

```text
任意处理中状态 -> FAILED
```

### 7.3 TaskRun 状态

QA Split 会创建：

```text
task_type  = split_document_qa_task
queue_name = qa
stage      = QA_SPLITTING
status     = RUNNING -> SUCCESS/FAILED
```

Embedding 会创建另一条：

```text
task_type  = embed_qa_pairs_task
queue_name = embedding
stage      = EMBEDDING -> INDEXING
status     = RUNNING -> SUCCESS/FAILED
```

### 7.4 进度值

当前代码中的关键进度如下：

| 进度 | 代码位置 | 含义 |
|---:|---|---|
| 20 | `DocumentParseService.parse_import_job()` | 解析任务开始 |
| 30 | `DocumentParseService.parse_import_job()` | Chunking 开始 |
| 40 | `DocumentParseService.parse_import_job()` | Chunk 已写入，准备 QA Split |
| 45 | `QaSplitService.split_import_job_for_task()` | QA Split worker 开始 |
| 65 | `QaSplitService.split_import_job_for_task()` | QA 对生成完成，准备 Embedding |
| 75 | `EmbeddingService.embed_import_job()` | Embedding worker 开始 |
| 90 | `EmbeddingService.embed_import_job()` | 向量准备完成，进入 Indexing |
| 100 | `EmbeddingService.embed_import_job()` | READY/COMPLETED |

这些数值适合用于页面的连续进度条，但不能直接当作 6 个稳定的离散阶段，因为 `CHUNKING`、`INDEXING` 是中间状态，且外部模型调用期间状态不会按内部每个子操作持续更新。

## 8. 异常、重试和恢复机制

### 8.1 QA Split 失败分类

| 场景 | 错误码示例 | 默认是否可重试 | 说明 |
|---|---|---:|---|
| 无有效 Child Chunk | `QA_PROVENANCE_NO_SPLITTABLE_CHUNKS` | 否 | 前置解析/切片没有可用输入 |
| 没有默认 QA 模型 | `QA_SPLIT_MODEL_NOT_CONFIGURED` | 否 | 需要管理员配置 |
| JSON 非法 | `QA_SPLIT_INVALID_OUTPUT` | 否 | 当前响应本身不可解析 |
| 字段或结构非法 | `QA_PROVENANCE_CONTRACT_INVALID` | 否 | 违反模型输出契约 |
| 缺少来源索引 | `QA_PROVENANCE_MISSING_CHUNK_INDEX` | 是 | 严格模式下模型可能重新生成正确结果 |
| 来源索引未知 | `QA_PROVENANCE_UNKNOWN_CHUNK_INDEX` | 是 | 模型返回了当前批次之外的索引 |
| quote/page 不匹配 | `QA_PROVENANCE_QUOTE_MISMATCH` | 是 | 模型生成内容与原文来源不一致 |
| 覆盖集合不完整 | `QA_PROVENANCE_COVERAGE_MISMATCH` | 是 | 模型没有完整声明处理结果 |
| Chunk generation 混合 | `QA_SPLIT_RUN_CONFIG_INVALID` | 是 | 需要重新生成或恢复一致的 Chunk collection |
| Provider 网络错误 | `PROVIDER_CONNECTION_ERROR` | 是 | 网络抖动或服务不可达 |
| Provider 认证失败 | `PROVIDER_UNAUTHORIZED` | 否 | API Key 或权限错误 |
| Provider 限流 | `PROVIDER_RATE_LIMITED` | 是 | 可能在退避后恢复 |
| 未预期内部错误 | `QA_SPLIT_INTERNAL_ERROR` | 是 | 交给任务重试，日志不暴露原始异常内容 |

“默认是否可重试”来自 `QaSplitValidationError.retryable` 或 `ProviderError.retryable`，最终是否真的重试还受 Celery 当前重试次数限制。

### 8.2 Celery 重试

**代码位置**

- `server/app/tasks/qa_tasks.py`
- `server/app/tasks/_common.py`

QA Task 配置：

```text
acks_late = true
max_retries = 3
```

失败时：

1. Service 先把失败状态提交到数据库；
2. `resolve_task_outcome()` 从 `TaskRun.error.retryable` 读取可重试标识；
3. `handle_failure()` 根据当前重试次数决定：
   - 仍有次数且可重试：调用 `task.retry()`；
   - 不可重试或次数耗尽：抛出 `TaskProcessingError`；
4. 退避时间为：

```text
min(600, 5 * 2^retries) 秒
```

### 8.3 业务接口重试

`ImportService.retry_job()` 支持从以下阶段重新入队：

```text
PARSING
CHUNKING
QA_SPLITTING
EMBEDDING
INDEXING
```

当失败阶段为 `QA_SPLITTING` 时，重新调用 `enqueue_qa_task()`；当失败阶段为 `EMBEDDING` 或 `INDEXING` 时，重新调用 `enqueue_embedding_task()`。

### 8.4 QA 成功但 Embedding 入队失败

这是一个独立的可靠性场景：

```text
QA 对已写入
job.stage = EMBEDDING
但 embedding 消息未成功发送
```

处理函数 `mark_embedding_enqueue_failed()` 会将：

- `Document.status` 改为 `FAILED`；
- `ImportJob.status` 改为 `FAILED`；
- `ImportJob.stage` 保留为 `EMBEDDING`；
- 错误码写为 `EMBEDDING_ENQUEUE_FAILED`；
- `TaskRun.error.retryable` 写为 `true`。

这样可以通过任务重试或业务重试从 Embedding 边界恢复。

## 9. 数据模型和持久化关系

### 9.1 DocumentChunk

文件：`server/app/models/qa_pair.py`

QA Split 重点使用：

- `chunk_index`：模型来源索引和 QA 对来源索引；
- `content`：quote 子串校验；
- `page_no`、`page_start`、`page_end`：页码校验；
- `title_path`：Prompt 上下文；
- `chunk_level`：只选择 `CHILD`；
- `status`：只选择 `ACTIVE`；
- `chunker_name`、`chunker_version`、`chunker_config_hash`：generation 绑定；
- `parent_chunk_id`：自适应层级关系；
- `embedding`、`search_text`、`chunk_metadata`：后置 Chunk 向量化。

### 9.2 QaPair

文件：`server/app/models/qa_pair.py`

QA Split 写入：

- `question`；
- `answer`；
- `quote`；
- `page_no`；
- `chunk_id`；
- `job_id`；
- `pair_index`；
- `status=ACTIVE`；
- `question_embedding=None`；
- `search_text=""`；
- `qa_metadata.sourceChunkIndex`。

Embedding 阶段再写入：

- `question_embedding`；
- `search_text`；
- `token_count`；
- `qa_metadata.embedding`。

### 9.3 ImportJob.options

QA Split 为后续 Embedding 写入：

```json
{
  "embedding": {
    "run_config_hash": "<当前 Chunk generation hash>"
  }
}
```

这是 QA Split 到 Embedding 的隐式数据契约。

### 9.4 TaskRun

QA Split 的 TaskRun 用于：

- 记录任务类型和队列；
- 记录 `QA_SPLITTING` 阶段；
- 记录成功或失败；
- 记录错误码、错误消息、retryable 和失败时间；
- 让任务层能够精确判断重试策略。

## 10. 相关接口和下游使用

### 10.1 查询 QA 对

**文件**

- `server/app/api/v1/documents.py`
- `server/app/repositories/qa_pair_repo.py`
- `server/app/schemas/qa_pair.py`

**接口**

```text
GET /api/v1/documents/{document_id}/qa-pairs
```

查询范围包含：

- `ACTIVE`；
- `EMBEDDING_FAILED`。

返回字段包括：

- `question`；
- `answer`；
- `quote`；
- `pageNo`；
- `chunkId`；
- `embeddingStatus`；
- `status`。

`embeddingStatus` 的计算规则：

```text
question_embedding 存在 -> READY
否则 -> QaPair.status
```

因此 QA Split 刚完成但尚未向量化时，页面可以看到 QA 内容，但 Embedding 状态仍不是 `READY`。

### 10.2 QA 对重新生成

**接口**

```text
POST /api/v1/documents/{document_id}/qa-regenerations
```

**代码**

- `server/app/api/v1/documents.py:126-145`
- `server/app/services/qa_split_service.py:637-643`

重新生成会：

1. 查找当前文档最近的 ImportJob；
2. 复用相同任务的 QA Split 主流程；
3. 重新生成 QA 对；
4. 成功后返回 `stage=EMBEDDING`；
5. 后续重新进入 Embedding。

### 10.3 检索依赖

检索仓储和服务通常只对：

- `DocumentStatus.READY`；
- `QaPair.status == ACTIVE`；
- 未软删除；
- 当前租户和权限范围内；

的数据执行最终检索。因此 QA 对写入并不等于立即可以检索，必须等 Embedding/Indexing 完成。

## 11. 测试证据和覆盖范围

### 11.1 QA Split 单元和服务测试

文件：`server/tests/test_qa_split_task.py`

已覆盖的行为包括：

- 非法 JSON 和缺少字段；
- 稳定的 provenance 指标；
- 没有可拆分 Chunk；
- 默认 QA 模型不存在；
- QA 对写入；
- 重复调用幂等；
- QA 失败时保留 Chunk 且不写入不完整 QA；
- QA Prompt 必须包含覆盖契约；
- 自适应 Chunk 严格来源校验；
- 未知 Chunk index；
- quote 不属于 Chunk；
- pageNo 超出 Chunk 页码范围；
- covered/skipped 覆盖不完整；
- quote 的 Unicode/空白归一化；
- 旧输出兼容匹配；
- 不把原文或模型原始输出写入错误日志；
- ProviderError 的错误码和 retryable 透传；
- 后续批次失败时不提前写入前面批次的 QA；
- Chunk generation 绑定。

### 11.2 批处理测试

文件：`server/tests/test_batching_pipeline.py`

覆盖：

- 字符预算贪心分组；
- 超预算普通 Chunk 独立成组；
- 自适应 Chunk 超预算直接失败；
- 批次数量不丢失。

### 11.3 任务可靠性测试

文件：`server/tests/test_task_reliability.py`

覆盖：

- QA 队列投递可以关闭自动 Embedding；
- Broker 失败日志不泄漏敏感异常内容；
- QA 成功后只在指定条件下投递 Embedding；
- Embedding 入队失败会持久化为可重试失败；
- 重试时能识别当前 TaskRun，而不是误更新旧 TaskRun；
- 重复 Embedding 投递不会重复创建 TaskRun。

### 11.4 Embedding 测试

文件：`server/tests/test_embedding_task.py`

覆盖：

- QA 对和 Chunk target 的向量化；
- 批量和并发；
- Provider 失败重试；
- 向量数量不匹配；
- 向量维度不匹配；
- `EMBEDDING` -> `INDEXING` -> `COMPLETED`；
- 文档从 `EMBEDDING` -> `READY`；
- Chunk generation 改变时拒绝旧绑定；
- QA 对最终为 `ACTIVE` 并可以被查询。

### 11.5 端到端测试

文件：`server/tests/e2e/test_v1_1_release_e2e.py`

主验收链路是：

```text
创建 ImportJob
  -> 绑定 Markdown 文件
  -> 执行完整导入管线
  -> Document.status == READY
  -> qaPairCount == 1
  -> 聊天检索命中引用
  -> OpenAI 兼容接口返回 citation
```

这证明 QA Split 生成的 QA 对最终可以进入向量化和检索链路。

## 12. 适配 6 步页面展示的建议

### 12.1 只修改页面显示时

如果需求是“页面显示 4 步改为 6 步”，但不要求后端任务真的产生 6 个独立可恢复阶段，可以采用以下映射：

| 页面步骤 | 页面文案 | 数据来源建议 |
|---:|---|---|
| 1 | 文档解析 | `PARSING` 或进度 `<30` |
| 2 | 知识切片 | `CHUNKING`，或解析完成后到 QA 开始前的过渡区间 |
| 3 | QA 文档生成 | `QA_SPLITTING`，进度 `40-65` |
| 4 | 向量化 | `EMBEDDING`，进度 `65-90` |
| 5 | 知识入库 | `INDEXING`，进度 `90-100` |
| 6 | 完成上架和可检索使用 | `COMPLETED`，文档 `READY` |

这种方案的优点是不会改变现有 Worker 编排、数据库状态和重试语义。

需要特别处理：

- `CHUNKING` 很短，轮询可能看不到；
- QA Split 内部的“批处理、模型生成、校验、QA 落库”没有单独进度；
- `EMBEDDING` 内部同时处理 QA target 和可选 Chunk target；
- `INDEXING` 是 Embedding Service 的最终写入阶段，不是独立 Celery 任务；
- 页面应将 `READY`/`COMPLETED` 作为“可检索”的唯一完成条件。

### 12.2 如果要求后端也有 6 个独立阶段

需要新增或改造：

1. `ImportJob.stage` 的阶段常量或统一枚举；
2. `DocumentStatus` 是否增加更细状态；
3. `TaskRun.stage` 的写入点；
4. `ImportService.retry_job()` 的阶段恢复分支；
5. API 返回的阶段和进度映射；
6. `resolve_task_outcome()` 对各阶段失败的判断；
7. QA Split 内部“知识切片”和“QA 文档生成”的可观测状态；
8. Embedding 内部“向量化”和“知识入库”的可观测状态；
9. 前端 `ImportJobTimeline` 的阶段定义；
10. 单元测试、任务可靠性测试和 E2E 测试。

不建议仅为页面文案把数据库状态改成 6 个值，却不增加对应的提交边界和恢复逻辑，否则会产生：

- 页面显示了阶段，但任务失败后无法从该阶段恢复；
- 轮询看到的阶段与 TaskRun 阶段不一致；
- `retry_job()` 无法正确选择重新入队的 Worker；
- QA 对已写入但 Embedding 未入队时无法区分；
- `INDEXING` 的最终事务边界被错误拆开，产生部分向量写入。

## 13. 关键函数索引

### 13.1 前置解析和知识切片

| 函数 | 文件 | 责任 |
|---|---|---|
| `parse_document_task` | `server/app/tasks/parse_tasks.py` | 解析任务入口及 QA 入队 |
| `parse_import_job` | `server/app/services/document_parse_service.py` | 文件解析和处理状态推进 |
| `_replace_parse_outputs` | `server/app/services/document_parse_service.py` | 解析产物和 Chunk 集合替换 |
| `_write_legacy_chunks` | `server/app/services/document_parse_service.py` | 旧版平铺 Chunk 写入 |
| `_write_adaptive_chunks` | `server/app/services/document_parse_service.py` | Parent/Child 自适应 Chunk 写入 |
| `_chunk_row` | `server/app/services/document_parse_service.py` | 生成 DocumentChunk ORM 行 |

### 13.2 QA Split

| 函数 | 文件 | 责任 |
|---|---|---|
| `split_document_qa_task` | `server/app/tasks/qa_tasks.py` | Celery Worker 入口 |
| `split_import_job_for_task` | `server/app/services/qa_split_service.py` | QA Split 事务主流程 |
| `_list_chunks` | `server/app/services/qa_split_service.py` | 选择当前有效 Child Chunk |
| `_default_model` | `server/app/services/qa_split_service.py` | 查询默认 QA_SPLIT 模型 |
| `_group_chunks` | `server/app/services/qa_split_service.py` | 按字符预算分批 |
| `_generate_qa_items` | `server/app/services/qa_split_service.py` | 并发生成和逐批校验 |
| `build_qa_split_prompt` | `server/app/services/qa_prompt_builder.py` | 构造模型 Prompt |
| `validate_qa_split_output` | `server/app/services/qa_split_service.py` | JSON、字段、来源、覆盖校验 |
| `_replace_qa_pairs` | `server/app/services/qa_split_service.py` | 替换 QA 对并绑定来源 |
| `_bind_embedding_run_config_hash` | `server/app/services/qa_split_service.py` | 绑定下游 Embedding generation |
| `log_qa_split_observability` | `server/app/services/qa_split_service.py` | 记录安全的覆盖率指标 |
| `_mark_failed` | `server/app/services/qa_split_service.py` | 持久化失败状态和 TaskRun.error |

### 13.3 QA 到 Embedding/知识入库

| 函数 | 文件 | 责任 |
|---|---|---|
| `enqueue_embedding_task` | `server/app/services/import_service.py` | 投递 Embedding 任务 |
| `embed_qa_pairs_task` | `server/app/tasks/embedding_tasks.py` | Embedding Worker 入口 |
| `embed_import_job` | `server/app/services/embedding_service.py` | 向量化、Indexing、完成提交 |
| `_list_qa_pairs` | `server/app/services/embedding_service.py` | 读取可向量化 QA |
| `_build_qa_targets` | `server/app/services/embedding_service.py` | 构造 QA 向量输入 |
| `_build_chunk_targets` | `server/app/services/embedding_service.py` | 构造 Child Chunk 向量输入 |
| `_embed_in_batches` | `server/app/services/embedding_service.py` | 批量并发向量化 |
| `_validate_vectors` | `server/app/services/embedding_service.py` | 数量和维度校验 |
| `_persist_targets` | `server/app/services/embedding_service.py` | 写入向量、搜索文本和元数据 |

## 14. 最终验收判断

从当前代码分析可以确认：

1. QA Split 的主入口和下游边界明确；
2. QA Split 会消费有效 Child Chunk，而不会重新切分原文；
3. QA 模型选择按租户和数据库默认配置驱动；
4. Prompt 要求严格 JSON 和来源覆盖契约；
5. 模型输出会经过 JSON、字段、页码、quote、Chunk index 和覆盖完整性校验；
6. 所有批次成功后才会替换 QA 对，避免早期批次部分落库；
7. QA 对保存了来源 Chunk、quote、页码和 generation 绑定信息；
8. QA Split 成功后状态是 `EMBEDDING`，不是最终完成；
9. Embedding 任务继续完成向量化、Indexing 和 `READY`/`COMPLETED`；
10. 失败信息、可重试属性和 TaskRun 记录可以支撑自动重试和人工重试；
11. 现有测试覆盖了 QA Split 的主流程、来源校验、批处理、可靠性和端到端可检索链路；
12. 页面拆成 6 步时，最小风险方案是新增前端展示映射，不改变当前后端阶段和事务边界；
13. 如果产品要求 6 个步骤均可被后端查询、重试和审计，则必须把它作为一次状态机和任务编排变更处理，而不只是修改页面文案。
