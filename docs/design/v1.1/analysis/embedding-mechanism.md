# 灵犀（Lingxi）Embedding 文本向量化机制说明

> 版本：V1.1
> 日期：2026-07-07
> 范围：`server/app/services/embedding_service.py`、`server/app/services/retrieval_service.py`、`server/app/integrations/model_providers/`、`server/app/db/types.py`
> 结论先行：**代码中不写死任何向量化模型，使用哪个模型完全由数据库配置决定**（管理后台"模型配置"页维护，按租户生效，改配置无需改代码或重启）

---

## 一、模型选择：配置驱动，按租户

每次向量化时，`EmbeddingService._default_model(tenant_id)`（`embedding_service.py:135`）执行一条联查，选出该租户满足以下条件的模型：

- `ModelConfig.capability == "EMBEDDING"` 且 `is_default == True` 且状态 `ACTIVE`；
- 所属 `ModelProvider` 状态 `ACTIVE`。

查不到则抛 `EMBEDDING_MODEL_MISSING`（"未配置默认 Embedding 模型"），任务失败并可重试。

配置存储：

| 表 | 关键字段 | 说明 |
|---|---|---|
| `ModelProvider` | `provider_type`、`base_url`、`encrypted_api_key`、`config` | API key 以 AES-GCM 信封加密存储（`core/secrets.py`，独立密钥可轮换） |
| `ModelConfig` | `capability`、`model_name`、`embedding_dimension`、`timeout_ms`、`is_default`、`config` | 按能力（CHAT / EMBEDDING / QA_SPLIT）区分，每租户每能力一个默认 |

维护入口：管理后台"模型配置"页或 `/api/v1` 的 provider / model CRUD 接口（`model_config_service.py`），支持在线连通性测试（测试结果写 `ModelCallLog`）。

## 二、支持的供应商类型（`integrations/model_providers/`）

| provider_type | 向量化实现 | 说明 |
|---|---|---|
| `OPENAI_COMPATIBLE` | `POST {base_url}/embeddings`，批量 `input=[...]` | 覆盖面最大：OpenAI 官方、阿里 DashScope 兼容模式、SiliconFlow、vLLM / 自建 BGE 服务等一切 OpenAI 兼容端点 |
| `INTERNAL_GATEWAY` | 同上（OPENAI_COMPATIBLE 子类） | 企业内网模型网关 |
| `OLLAMA` | `POST /api/embeddings`，每条文本一次请求（循环，无批量接口） | 本地 Ollama 模型 |
| `CLAUDE` | **不支持**，`embed_texts` 抛 `PROVIDER_EMBEDDING_UNSUPPORTED` | Anthropic 没有 embedding API |
| Mock（`mock://` base_url） | SHA256 派生的确定性伪向量 | 测试 / 本地开发专用，无网络 I/O |

实际使用的是 text-embedding-3、bge-m3 还是 qwen text-embedding-v3，取决于管理员配置的 `model_name` 与 `base_url`。

所有真实 provider 共享 `HttpProvider` 底座（`model_providers/base.py`）：超时取 `timeout_ms`（默认 30s）、对 408/429/5xx 与网络错误按 `min(8, 0.5·2ⁿ)` 退避重试、错误归一化为 `ProviderError(code, retryable)`。

## 三、写入侧流程（`EmbeddingService.embed_import_job`）

导入链路的第三段 Celery 任务 `embed_qa_pairs_task`（embedding 队列）触发：

1. **只对每个 QA 对的 question 做向量化**（`embedding_service.py:96`：`[item.question for item in qa_pairs]`）。这是系统"用户问题 vs 预生成问题匹配"的架构选择——answer / quote 只进 jieba 分词的全文索引（`search_text` → tsvector），不进向量通道；
2. **批量 + 并发 + 重试**（环境变量控制）：
   - 按 `EMBEDDING_BATCH_SIZE=64` 切批（供应商单次调用有批量上限）；
   - `run_ordered`（`services/_batching.py`）线程池并发，上限 `EMBEDDING_MAX_CONCURRENCY=4`，结果保序合并；
   - 每批对可重试错误指数退避重试 `EMBEDDING_BATCH_MAX_RETRIES=2` 次；仍失败则任务级失败，交由 Celery 层按 `TaskRun.error.retryable` 决定整任务重试（最多 3 次）；
3. **双重校验**：返回向量数量 == 请求文本数（`EMBEDDING_RESULT_COUNT_MISMATCH`）；每个向量维度 == `model_config.embedding_dimension`，默认 1536（`EMBEDDING_DIMENSION_MISMATCH`）；
4. **落库**：向量写 `qa_pairs.question_embedding`；同时重建 `search_text`（jieba 分词，见 `integrations/tokenizers/`）与 `token_count`；文档状态推进到 `READY`，任务/文档计数器更新，全程一个事务提交；
5. 失败路径：QA 对标记 `EMBEDDING_FAILED`、文档 `FAILED`、错误码与 retryable 落 `TaskRun.error`，支持从 EMBEDDING 阶段断点重试。

## 四、查询侧

`RetrievalService._embed_query`（`retrieval_service.py:106`）用**同一个租户默认 EMBEDDING 模型**将用户问题转成查询向量——写读两端模型天然一致，不存在"索引用 A 模型、查询用 B 模型"的漂移。模型未配置或不可达时有降级路径（`_fallback_embedding`，4 维伪向量），仅为本地 / 测试兜底，生产不会走到。

查询向量经 pgvector 余弦检索（`retrieval_repo._vector_search_pg`，`<=>` 走 HNSW 索引）取 top-k，与 jieba 全文检索双路 RRF 融合。

## 五、存储与维度约束（2026-07-08 更新：维度已配置化）

`qa_pairs.question_embedding` 的列类型是 `EmbeddingVector(settings.embedding_vector_dimension)`（`models/qa_pair.py` + `db/types.py`），维度由环境变量 **`EMBEDDING_VECTOR_DIMENSION`（默认 1024）** 决定：

- PostgreSQL 上编译为 pgvector 的 `vector(N)` 列，迁移 0001 建有 HNSW 余弦索引（部分索引：ACTIVE 且未删除）；
- SQLite（测试环境）退化为 JSON 列，不校验维度；
- 迁移 `0003_embedding_vector_dimension` 负责把存量数据库的列对齐到当前配置：列维度与配置不一致时执行 `ALTER COLUMN ... TYPE vector(N)`（空表/全 NULL 即时完成；已有异维向量会失败——这是正确行为，跨维度向量无法转换，必须重嵌入）。

**约束**：`EMBEDDING_VECTOR_DIMENSION` 必须与默认 Embedding 模型的输出维度一致（如 bge-m3 / qwen text-embedding-v3 为 1024，OpenAI text-embedding-3-small 为 1536）。修改维度的操作顺序：改 env → `alembic upgrade head`（空表）或先清空/重嵌入存量向量 → 重启 API 与 worker。**不同模型的向量空间不可混用——即使维度相同，换模型也必须全量重嵌入。**

## 六、配置项速查

| 配置 | 位置 | 默认 | 说明 |
|---|---|---|---|
| 模型 / 供应商 / API key / 维度 / 超时 | 数据库（管理后台维护） | — | 运行时热生效，按租户 |
| `EMBEDDING_VECTOR_DIMENSION` | 环境变量 | 1024 | 向量列维度，须与默认模型输出一致（见 §五） |
| `EMBEDDING_BATCH_SIZE` | 环境变量 | 64 | 单次供应商调用的文本数 |
| `EMBEDDING_MAX_CONCURRENCY` | 环境变量 | 4 | 批次并发上限（线程池） |
| `EMBEDDING_BATCH_MAX_RETRIES` | 环境变量 | 2 | 单批瞬时错误重试次数 |

## 七、已知限制

- ~~向量列维度固定 1536~~（已解决：2026-07-08 起由 `EMBEDDING_VECTOR_DIMENSION` 配置，默认 1024，迁移 0003 对齐存量库，见 §五）；
- **OpenAI 兼容适配器的 `embed_texts` 不透传 `dimensions` 参数**（`openai_compatible.py:73`，请求体仅 `{"model", "input"}`）——需要用维度参数改变模型默认输出维度的场景（如 qwen v4 要输出 1536）暂不支持，只能拿到模型默认维度（见 §八）；
- Ollama 适配器无批量接口，大文档向量化吞吐受限于逐条请求；
- 只嵌入 question——知识点若未被 QA 拆分覆盖则向量通道不可达（chunk 级第三路召回列入 [llamaindex-comparison.md](./llamaindex-comparison.md) 的改进建议）；
- 真实 embedding 调用不写 `ModelCallLog`（仅连通性测试写），无 token 计量。

## 八、常见 Embedding 模型配置指引（2026-07-08 追加，同日随维度配置化修订）

### 通用配置步骤

管理后台"模型配置"页（或 `/api/v1` 对应接口）：

1. **新建供应商**：选 `provider_type`、填 `base_url` 与 API Key（加密存储）；
2. **新建模型**：能力选 `EMBEDDING`，填 `model_name`、`embedding_dimension`、超时；
3. **设为默认**（每租户每能力一个默认，入库与检索自动使用）；
4. 点**连接测试**验证连通性。

### 两个约束（决定各模型的配置路径）

1. 模型输出维度必须等于 `EMBEDDING_VECTOR_DIMENSION`（**当前默认 1024**）；维度不一致时改 env + `alembic upgrade head` 对齐列（见 §五）；
2. `embed_texts` 请求体只有 `{"model", "input"}`，配置里的 `dimensions` **不会**发给 API——所以只能使用模型的**默认输出维度**，无法用维度参数改变输出（chat 通道有 maxTokens/temperature 透传，embedding 通道无对应实现）。

### ① 1024 维模型（当前默认维度）——开箱即用

**bge-m3**（固定 1024 维）：

| 字段 | Ollama 本地 | SiliconFlow 托管 |
|---|---|---|
| provider_type | `OLLAMA` | `OPENAI_COMPATIBLE` |
| base_url | `http://localhost:11434` | `https://api.siliconflow.cn/v1` |
| model_name | `bge-m3` | `BAAI/bge-m3` |
| embedding_dimension | `1024` | `1024` |

注意 Ollama 适配器逐条请求（无批量），大库入库吞吐较低。

**qwen text-embedding-v3 / v4**（DashScope 兼容模式，两者默认输出均为 1024 维）：

| 字段 | 值 |
|---|---|
| provider_type | `OPENAI_COMPATIBLE` |
| base_url | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| model_name | `text-embedding-v3`（或 `text-embedding-v4`） |
| embedding_dimension | `1024` |

### ② 其他默认维度的模型——改 env + 迁移

如 OpenAI `text-embedding-3-small`（1536 维）：`EMBEDDING_VECTOR_DIMENSION=1536` → `alembic upgrade head`（空表即时完成，有数据须先清空/重嵌入）→ 重启 API 与 worker → 按通用步骤配置（base_url `https://api.openai.com/v1`，embedding_dimension 1536）。

### ③ 需要用 `dimensions` 参数改变输出维度的场景——暂不支持

例如想让 qwen v4 输出 1536 而非默认 1024：受约束 2 限制（`embed_texts` 不透传 `dimensions`），需先给适配器加透传（约 3 行，仿 chat 通道 `maxTokens` 写法）。在默认 1024 维下通常无此需求。

### 换模型的共同注意事项

- 不同模型的向量空间不可混用——**即使维度相同，换模型后存量向量也必须全量重嵌入**，否则新查询向量与旧文档向量不在同一空间，检索质量静默崩坏；
- 系统目前**没有全局重嵌入工具**：逐文档"重新生成 QA"会触发该文档重嵌入；全库范围需要编写类似 `backfill_search_text` 的批量脚本（列入待办）；
- `embedding_dimension` 字段必须与模型实际输出一致——它是入库前的校验依据（`EMBEDDING_DIMENSION_MISMATCH`）。
