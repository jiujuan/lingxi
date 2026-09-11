# QA Split 长耗时治理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 QA Split 从“整篇文档一次性等待、失败后整体重跑”改造成可按批次控制规模、区分超时阶段、有限重试、可断点恢复、完整校验后一次性发布的处理流水线。

**Architecture:** 保留当前 `split_document_qa_task -> QaSplitService -> ProviderAdapter` 主链路，在 Provider HTTP 层增加分阶段 timeout 和 overall deadline，在 QA Service 层增加 token 预算分组、批次级重试和二分降载，在数据库层增加 QA Split Run/Batch 临时结果。只有所有批次成功并通过 provenance 校验后，才在单个事务中替换 ACTIVE `QaPair`，随后沿用现有 Embedding 的最终锁、向量校验和 READY 发布逻辑。

**Tech Stack:** Python 3、FastAPI、Celery、SQLAlchemy、Alembic、httpx、Pydantic、PostgreSQL/SQLite 测试数据库、React/TypeScript、pytest、Playwright、Prometheus 文本指标。

---

## 0. 范围、现状和实施约束

### 0.1 005 文档要求到任务的映射

| 005 方案 | 本计划任务 | 结果 |
|---|---|---|
| L1 单批次输入和输出规模 | Task 1、Task 4 | 从字符贪心分组升级为带固定 Prompt 开销和输出预留的 token budget |
| L2 并发和背压 | Task 6 | Provider/模型维度的并发上限、429/5xx/timeout 后降载 |
| L3 分离 timeout | Task 2、Task 3 | connect/write/read-idle/overall 四类预算及 timeout phase |
| L4 批次级重试和超时拆分 | Task 5 | 有限重试、超时后二分、不可重试错误终止 |
| L5 checkpoint | Task 7、Task 8 | Run/Batch 持久化、恢复、临时结果与 ACTIVE 发布隔离 |
| L6 Provider 专属策略 | Task 9 | Ollama、OpenAI-compatible、DeepSeek 参数白名单 |
| L7 观测和动态调参 | Task 10、Task 11、Task 12 | ModelCallLog、metrics、管理端配置和日志展示 |
| Embedding 边界 | Task 13 | 验证 QA 未完整发布时 Embedding 不可读取，保持现有向量最终事务 |
| 长 PDF 验收 | Task 14 | 真实模型/模拟慢模型、失败恢复、最终 READY 证据 |

### 0.2 当前代码基线

现有 QA 主流程为：

```text
server/app/tasks/qa_tasks.py:
    split_document_qa_task()
        -> QaSplitService.split_import_job_for_task()
            -> _list_chunks()
            -> _default_model()
            -> build_provider_adapter()
            -> _group_chunks()
            -> _generate_qa_items()
                -> run_ordered()
                -> adapter.generate_qa_pairs()
                -> validate_qa_split_output()
            -> _replace_qa_pairs()
            -> Document.status = EMBEDDING
```

当前关键限制：

1. `server/app/core/config.py` 只有 `QA_SPLIT_MAX_BATCH_CHARS=6000` 和 `QA_SPLIT_MAX_CONCURRENCY=4`。
2. `server/app/integrations/model_providers/base.py` 用一个 `httpx.Client(timeout=self.timeout_seconds)` 同时覆盖连接、写入和读取。
3. `server/app/services/qa_split_service.py::_generate_qa_items()` 等待所有批次返回后才统一校验和写入。
4. `ModelCallLog` 目前只有 `run_id`、`latency_ms`、空的 `token_usage` 和错误字段，没有批次、输入规模、timeout phase。
5. 当前没有独立的 QA Split Run/Batch 表；`ImportJob.options` 仅保存 Embedding 的 `run_config_hash`。
6. `server/app/services/embedding_service.py` 已经有批处理、批次 retry、数量/维度校验和最终持久化事务，本计划不重写这套机制，只增加 QA 发布边界的验证。

### 0.3 全局不可违反的约束

1. `QA_PROVENANCE_CONTRACT_INVALID`、`QA_SPLIT_INVALID_OUTPUT`、`PROVIDER_UNAUTHORIZED` 等确定性错误不得进入网络 timeout 重试循环。
2. timeout 后二分必须保留原始 `chunkIndex`、批次顺序和 provenance 覆盖完整性，不能通过重新编号掩盖来源错误。
3. 未完成的 QA Batch 结果只能保存在临时 Run 中，不能进入 ACTIVE `QaPair`、Embedding 输入或检索集合。
4. 只有全部 Batch 完成、输出通过 `validate_qa_split_output()`、所有当前 Chunk 被覆盖或明确 skipped 后，才能调用 `_replace_qa_pairs()`。
5. 日志不得保存 Prompt 正文、完整模型输出、API Key、PDF 原文或敏感 quote；只保存计数、哈希、错误码和安全元数据。
6. 兼容现有 Ollama、OpenAI-compatible、Claude、Internal Gateway、Mock Provider、Celery 任务参数和历史已入队任务。
7. 旧数据库升级后，未完成的旧 QA 任务必须按“无 checkpoint 的新 Run”处理，不得把旧 `TaskRun` 误认为已完成 Batch。

## 文件责任地图

### 必须修改的现有文件

- `server/app/core/config.py`
  - 新增 QA token budget、retry、backpressure 和 timeout 默认值。
- `server/app/integrations/model_providers/base.py`
  - 定义 `ProviderTimeouts`、整体 deadline、httpx 分阶段 timeout、统一 ProviderError。
- `server/app/integrations/model_providers/registry.py`
  - 将完整 timeout 配置传给适配器，同时保持旧 `timeout_ms` 兼容。
- `server/app/integrations/model_providers/ollama.py`
  - 传递 Ollama `keep_alive`、结构化输出和模型专属参数，保留 `/api/chat` 和 `/api/embeddings`。
- `server/app/integrations/model_providers/openai_compatible.py`
  - 传递白名单参数、检查 `finish_reason`、修复 `_extract_message()` 的 Provider 上下文。
- `server/app/models/model_config.py`
  - 增加四阶段 timeout、Provider 专属参数和 QA Run/Batch 关系。
- `server/app/schemas/model_config.py`
  - 增加创建、更新、响应字段及范围校验。
- `server/app/services/model_config_service.py`
  - 校验 timeout、合并模型配置、连接测试返回完整诊断。
- `server/app/api/v1/model_config.py`
  - 保持现有 API 路径，扩展 JSON 请求/响应字段。
- `server/app/services/qa_split_service.py`
  - token 分组、批次执行、retry/split、checkpoint、最终发布。
- `server/app/tasks/qa_tasks.py`
  - 将 Celery 重试入口绑定到可恢复 Run，不重复已成功 Batch。
- `server/app/services/_batching.py`
  - 增加可取消/限流/逐批回调能力，保持 `run_ordered()` 旧行为。
- `server/app/models/model_config.py`
  - 扩充 `ModelCallLog` 观测字段。
- `server/app/repositories/model_call_log_repo.py`
  - 增加批次、timeout phase、Provider 和模型过滤。
- `server/app/services/log_query_service.py`
  - 输出新增安全诊断字段。
- `server/app/schemas/logs.py`
  - 扩展模型调用日志响应。
- `server/app/core/metrics.py`
  - 增加 QA batch、timeout、retry、split、backpressure 指标。
- `server/app/services/embedding_service.py`
  - 增加“只读取已发布 QA”断言和回归保护，不改变现有 embedding 算法。
- `server/app/db/migrations/versions/0008_qa_split_long_running.py`
  - 新增 SQLAlchemy 模型字段和 QA Run/Batch 表。

### 可以新增的聚焦文件

- `server/app/services/qa_split_batching.py`
  - token 预算分组、Batch identity、二分算法和 batch retry policy。
- `server/app/services/qa_split_run_service.py`
  - Run/Batch 状态迁移、checkpoint、恢复和发布前查询。
- `server/app/schemas/qa_split_run.py`
  - 内部持久化对象的输入/输出类型，避免把 JSON dict 散落在任务代码中。
- `server/app/models/qa_split_run.py`
  - `QaSplitRun`、`QaSplitBatch` ORM 模型。

### 测试和验收文件

- `server/tests/test_model_providers_http.py`
- `server/tests/test_qa_split_task.py`
- `server/tests/test_batching_pipeline.py`
- `server/tests/test_model_config.py`
- `server/tests/test_logs_observability.py`
- `server/tests/test_embedding_task.py`
- `server/tests/test_qa_split_run.py`（新增）
- `server/tests/e2e/test_v1_1_release_e2e.py`
- `web/admin/tests/t19_qa_split_timeout_playwright.py`（新增）
- `docs/development/v1.1/acceptance/qa-split-long-running/`（新增验收证据目录）

## Task 1: 建立 QA Split 运行参数和配置校验

**实现目标和功能：** 将单一字符预算和单一 timeout 变成显式、可校验、可回滚的运行参数。第一阶段仍允许只配置旧 `timeoutMs`，系统按兼容规则推导新字段，避免历史模型配置立即失效。

**Files:**
- Modify: `server/app/core/config.py`
- Modify: `server/app/models/model_config.py`
- Modify: `server/app/schemas/model_config.py`
- Modify: `server/app/services/model_config_service.py`
- Modify: `server/app/api/v1/model_config.py`
- Test: `server/tests/test_config.py`
- Test: `server/tests/test_model_config.py`

### 数据契约

新增 ModelConfig 字段，数据库字段使用 snake_case，API 使用现有 Pydantic alias：

```json
{
  "timeoutMs": 30000,
  "connectTimeoutMs": 5000,
  "writeTimeoutMs": 30000,
  "readIdleTimeoutMs": 180000,
  "overallTimeoutMs": 240000,
  "maxTokens": 4096,
  "config": {
    "qaSplit": {
      "maxInputTokens": 4096,
      "reservedOutputTokens": 2048,
      "maxRetries": 1,
      "maxSplitDepth": 1
    }
  }
}
```

### 具体改动

1. 在 `server/app/core/config.py` 增加：

```python
qa_split_max_input_tokens: int = field(
    default_factory=lambda: int(os.getenv("QA_SPLIT_MAX_INPUT_TOKENS", "4096"))
)
qa_split_reserved_output_tokens: int = field(
    default_factory=lambda: int(os.getenv("QA_SPLIT_RESERVED_OUTPUT_TOKENS", "2048"))
)
qa_split_max_retries: int = field(
    default_factory=lambda: int(os.getenv("QA_SPLIT_MAX_RETRIES", "1"))
)
qa_split_max_split_depth: int = field(
    default_factory=lambda: int(os.getenv("QA_SPLIT_MAX_SPLIT_DEPTH", "1"))
)
qa_split_initial_concurrency: int = field(
    default_factory=lambda: int(os.getenv("QA_SPLIT_INITIAL_CONCURRENCY", "1"))
)
qa_split_min_concurrency: int = field(
    default_factory=lambda: int(os.getenv("QA_SPLIT_MIN_CONCURRENCY", "1"))
)
qa_split_max_concurrency: int = field(
    default_factory=lambda: int(os.getenv("QA_SPLIT_MAX_CONCURRENCY", "4"))
)
```

保留 `qa_split_max_batch_chars` 一版作为兼容 fallback，但新代码优先使用 token budget。

2. 在 `ModelConfig` 增加：

```python
connect_timeout_ms: Mapped[int | None] = mapped_column(Integer)
write_timeout_ms: Mapped[int | None] = mapped_column(Integer)
read_idle_timeout_ms: Mapped[int | None] = mapped_column(Integer)
overall_timeout_ms: Mapped[int | None] = mapped_column(Integer)
```

3. 在 `ModelConfigCreateRequest`、`ModelConfigUpdateRequest`、`ModelConfigResponse` 增加对应 alias 和范围限制。`timeoutMs` 继续保留为旧客户端兼容字段。

4. 在 `ModelConfigService.create_model_config()` 和 `update_model_config()` 中增加 `_validate_timeouts()`：

```python
def _validate_timeouts(
    *,
    timeout_ms: int | None,
    connect_timeout_ms: int | None,
    write_timeout_ms: int | None,
    read_idle_timeout_ms: int | None,
    overall_timeout_ms: int | None,
) -> None:
    values = {
        "timeoutMs": timeout_ms,
        "connectTimeoutMs": connect_timeout_ms,
        "writeTimeoutMs": write_timeout_ms,
        "readIdleTimeoutMs": read_idle_timeout_ms,
        "overallTimeoutMs": overall_timeout_ms,
    }
    for name, value in values.items():
        if value is not None and (isinstance(value, bool) or value < 100):
            raise bad_request("INVALID_MODEL_TIMEOUT", f"{name} 必须不小于 100ms")
    if (
        overall_timeout_ms is not None
        and read_idle_timeout_ms is not None
        and overall_timeout_ms < read_idle_timeout_ms
    ):
        raise bad_request(
            "INVALID_MODEL_TIMEOUT",
            "overallTimeoutMs 不能小于 readIdleTimeoutMs",
        )
```

推导规则固定为：

```text
connect = connectTimeoutMs or min(timeoutMs, 10000)
write = writeTimeoutMs or timeoutMs
read_idle = readIdleTimeoutMs or timeoutMs
overall = overallTimeoutMs or timeoutMs
```

不把 `overall` 自动设置成小于 `read_idle`。

### 边界和约束

- 旧配置只有 `timeoutMs=180000` 时，QA 仍必须可以运行。
- `overallTimeoutMs` 小于 `readIdleTimeoutMs` 必须在 API 层拒绝。
- Embedding、Chat、QA_SPLIT 共用字段，但只有 QA Split 使用 batch retry/split 参数。
- 不能把 `config` 任意字典中的未知 timeout 字段静默当作正式字段。

### 测试和验证

```powershell
pytest server/tests/test_config.py server/tests/test_model_config.py -q
```

必须覆盖：

1. 旧 `timeoutMs` 创建配置成功。
2. 四个新 timeout 全部返回 API。
3. 小于 100ms、overall 小于 read idle、bool 伪装整数均返回 `INVALID_MODEL_TIMEOUT`。
4. 默认值与环境变量覆盖正确。

### 验收证据

- API 测试响应中同时出现 `timeoutMs`、`connectTimeoutMs`、`writeTimeoutMs`、`readIdleTimeoutMs`、`overallTimeoutMs`。
- 终端保存 pytest 输出。
- 追加 `docs/development/v1.1/acceptance/qa-split-long-running/task-01-model-timeout-config.json`，只保存非敏感配置和断言结果。

**Done when**

- 新旧配置均能创建、读取、更新。
- 所有非法 timeout 组合在 API 层被拒绝。
- `pytest server/tests/test_config.py server/tests/test_model_config.py -q` 全部通过。

**Commit:**

```powershell
git add server/app/core/config.py server/app/models/model_config.py server/app/schemas/model_config.py server/app/services/model_config_service.py server/app/api/v1/model_config.py server/tests/test_config.py server/tests/test_model_config.py
git commit -m "feat: define QA split timeout configuration"
```

## Task 2: Provider HTTP 层分离 connect/write/read/overall timeout

**实现目标和功能：** 让 Provider 能明确区分连接建立、请求写入、响应读取和整体 deadline，错误码不再把所有 `ReadTimeout` 都描述成“连接失败”。

**Files:**
- Create: `server/app/integrations/model_providers/timeouts.py`
- Modify: `server/app/integrations/model_providers/base.py`
- Modify: `server/app/integrations/model_providers/registry.py`
- Modify: `server/app/services/qa_split_service.py`
- Modify: `server/app/services/embedding_service.py`
- Test: `server/tests/test_model_providers_http.py`
- Test: `server/tests/test_qa_split_task.py`

### 类型和函数契约

在 `timeouts.py` 定义：

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class ProviderTimeouts:
    connect_seconds: float
    write_seconds: float
    read_idle_seconds: float
    pool_seconds: float
    overall_seconds: float

    @classmethod
    def from_config(
        cls,
        *,
        legacy_timeout_ms: int | None,
        connect_timeout_ms: int | None,
        write_timeout_ms: int | None,
        read_idle_timeout_ms: int | None,
        overall_timeout_ms: int | None,
    ) -> "ProviderTimeouts": ...
```

在 `BaseProvider` 增加：

```python
@property
def timeouts(self) -> ProviderTimeouts: ...

def _remaining_deadline(self, started_at: float) -> float: ...

def _httpx_timeout(self, started_at: float) -> httpx.Timeout: ...

def _timeout_error(
    self,
    exc: httpx.TimeoutException,
    *,
    endpoint: str,
    phase: str,
) -> ProviderError: ...
```

`_request_json()` 和 `_stream_lines()` 每次 retry 都必须重新计算剩余 overall budget；不能每次重试都获得完整的 `overall_timeout_ms`。

### 错误码和 phase

| 条件 | error code | timeout phase |
|---|---|---|
| DNS/TCP/TLS/代理连接超时 | `PROVIDER_CONNECTION_TIMEOUT` | `connect` |
| 请求体发送超时 | `PROVIDER_WRITE_TIMEOUT` | `write` |
| 连接池等待超时 | `PROVIDER_POOL_TIMEOUT` | `pool` |
| 首 token 或响应块等待超时 | `PROVIDER_INFERENCE_TIMEOUT` | `read` |
| overall deadline 到期 | `PROVIDER_OVERALL_TIMEOUT` | `overall` |

以上错误都带：

```text
provider_name
provider_type
model_name
endpoint
timeout_ms
timeout_phase
```

错误消息示例：

```text
模型推理读取超时（供应商：Gemma；模型：gemma3；类型：Ollama；
endpoint：http://localhost:11434/api/chat；超时：180 秒；阶段：read）
```

### 具体实现要求

1. `httpx.Client` 使用：

```python
httpx.Timeout(
    connect=timeouts.connect_seconds,
    write=timeouts.write_seconds,
    read=timeouts.read_idle_seconds,
    pool=timeouts.pool_seconds,
)
```

2. 每次 HTTP 请求记录 `started_at = time.monotonic()`，在调用前检查：

```python
remaining = overall_seconds - (time.monotonic() - started_at)
if remaining <= 0:
    raise ProviderError("PROVIDER_OVERALL_TIMEOUT", ...)
```

3. 不要在 `ProviderError` 中保存请求正文。

4. `build_provider_adapter()` 增加可选的四个 timeout 参数；旧 `timeout_ms` 仍写入 merged config，便于 MockProvider 和历史调用继续工作。

5. `qa_split_service.py` 和 `embedding_service.py` 创建 adapter 时传递 ModelConfig 的四个字段。

### 边界和约束

- `httpx.ConnectTimeout` 不得再被错误地映射成 inference timeout。
- `httpx.ReadTimeout` 只有在 `timeout_phase="inference"` 时映射为 `PROVIDER_INFERENCE_TIMEOUT`。
- overall timeout 触发后不得继续 retry。
- 连接成功但模型迟迟不返回数据时，必须显示“读取/推理超时”，不能显示“连接失败”。
- MockProvider 不应创建真实 httpx timeout，但必须能接受新增参数。

### 测试和验证

在 `server/tests/test_model_providers_http.py` 增加：

```python
@pytest.mark.parametrize(
    ("exception_type", "expected_code", "expected_phase"),
    [
        (httpx.ConnectTimeout, "PROVIDER_CONNECTION_TIMEOUT", "connect"),
        (httpx.WriteTimeout, "PROVIDER_WRITE_TIMEOUT", "write"),
        (httpx.ReadTimeout, "PROVIDER_INFERENCE_TIMEOUT", "read"),
        (httpx.PoolTimeout, "PROVIDER_POOL_TIMEOUT", "pool"),
    ],
)
def test_timeout_phase_is_preserved(...): ...

def test_overall_timeout_is_not_reset_by_retry(...): ...
```

运行：

```powershell
pytest server/tests/test_model_providers_http.py -q
```

### 验收证据

- 四类异常分别产生四类可定位错误码。
- 错误消息含 Provider、model、endpoint、超时秒数和 phase。
- retry 日志显示剩余 overall budget，而不是每次重新开始计时。

**Done when**

- `BaseProvider` 不再使用单个 `timeout_seconds` 控制全部 HTTP 阶段。
- 所有真实 Provider 通过统一 timeout contract。
- `test_model_providers_http.py` 全部通过，旧 Provider 测试无回归。

**Commit:**

```powershell
git add server/app/integrations/model_providers/timeouts.py server/app/integrations/model_providers/base.py server/app/integrations/model_providers/registry.py server/app/services/qa_split_service.py server/app/services/embedding_service.py server/tests/test_model_providers_http.py server/tests/test_qa_split_task.py
git commit -m "feat: separate provider timeout phases"
```

## Task 3: 首 Token、read-idle、流式响应和 finish_reason 治理

**实现目标和功能：** 避免“模型持续输出但整体耗时较长”与“连接已经卡死”被同一种 timeout 处理；为未来流式 QA 调用和当前 Chat/Embedding 调用提供一致的读取诊断。

**Files:**
- Modify: `server/app/integrations/model_providers/base.py`
- Modify: `server/app/integrations/model_providers/openai_compatible.py`
- Modify: `server/app/integrations/model_providers/ollama.py`
- Modify: `server/app/integrations/model_providers/claude.py`
- Test: `server/tests/test_model_providers_http.py`
- Test: `server/tests/test_openai_compatible_api.py`

### 具体改动

1. `ProviderTimeouts` 增加 `first_byte_seconds`；若没有独立配置，则取 `read_idle_seconds`。
2. `_stream_lines()` 进入响应后记录 `first_byte_seen`，第一个非空 line 超过 `first_byte_seconds` 抛出 `PROVIDER_INFERENCE_TIMEOUT`，后续两个非空 line 间超过 `read_idle_seconds` 也抛出同一错误，但 `timeout_phase` 分别为 `first_byte`、`read_idle`。
3. 流式读取仍然受 `overall_seconds` 限制。
4. `OpenAICompatibleProvider._extract_message()` 改为实例方法，不能在 `@staticmethod` 中引用 `self`。
5. `_extract_message()` 检查：

```python
finish_reason = choices[0].get("finish_reason")
if finish_reason == "length":
    raise ProviderError(
        "PROVIDER_OUTPUT_TRUNCATED",
        "模型输出因达到 token 上限而截断",
        retryable=False,
        **self._provider_error_context(endpoint=endpoint),
    )
```

6. `OllamaProvider._post_chat()` 检查 Ollama `done_reason`；如果是 `length`，返回 `PROVIDER_OUTPUT_TRUNCATED`。
7. 读取响应 body 失败时保持 `PROVIDER_BAD_RESPONSE`，不能包装成网络 timeout。

### 边界和约束

- 非流式 `POST /chat/completions` 的 server processing 时间必须由 read timeout 和 overall timeout 覆盖。
- 空白 SSE line 不得刷新 read-idle 计时。
- `[DONE]` 不视为文本 token，但必须正常结束。
- 供应商没有 `finish_reason` 时保持兼容，不假设字段必然存在。
- 不在日志中保存流式完整输出。

### 测试和验证

```powershell
pytest server/tests/test_model_providers_http.py server/tests/test_openai_compatible_api.py -q
```

新增断言：

1. first byte 超时和后续 read idle 超时的 phase 不同。
2. OpenAI-compatible `finish_reason=length` 返回稳定错误码。
3. Ollama `done_reason=length` 返回稳定错误码。
4. 正常 SSE 仍拼接为完整文本。

**Done when**

- 慢模型持续产生 token 不会因为单个空闲片段误报 overall timeout。
- 连接保持但服务端不输出时能报 `PROVIDER_INFERENCE_TIMEOUT`。
- 截断输出不会进入 QA provenance validator。

## Task 4: 用 token budget 替换纯字符贪心分组

**实现目标和功能：** 在 Prompt 固定开销、文档标题、Chunk 元数据、输出预留都计入后再分组，减少超大批次导致的推理超时和 JSON 截断。

**Files:**
- Create: `server/app/services/qa_split_batching.py`
- Modify: `server/app/services/qa_prompt_builder.py`
- Modify: `server/app/services/qa_split_service.py`
- Modify: `server/app/core/service_factory.py`
- Test: `server/tests/test_qa_split_task.py`
- Test: `server/tests/test_batching_pipeline.py`
- Test: `server/tests/test_chunk_tokenizer.py`

### 类型和函数契约

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class QaBatch:
    batch_index: int
    chunks: tuple[DocumentChunk, ...]
    estimated_input_tokens: int
    reserved_output_tokens: int
    input_hash: str

def estimate_qa_prompt_tokens(
    document: Document,
    chunks: list[DocumentChunk],
    token_counter: TokenCounter,
) -> int: ...

def group_qa_chunks(
    document: Document,
    chunks: list[DocumentChunk],
    *,
    token_counter: TokenCounter,
    max_input_tokens: int,
    reserved_output_tokens: int,
) -> list[QaBatch]: ...

def split_qa_batch(batch: QaBatch) -> tuple[QaBatch, QaBatch]: ...
```

### 分组算法

每个候选批次必须满足：

```text
estimate(system prompt + document metadata + chunks) <= max_input_tokens
```

`reserved_output_tokens` 不放入输入计算，但必须在创建 Batch 时写入 metadata，用于校验：

```text
max_input_tokens + reserved_output_tokens <= model context budget
```

具体规则：

1. 按当前 `_list_chunks()` 的 `chunk_index` 排序。
2. 逐个加入 Chunk；加入后超过预算时，先提交当前组，再以该 Chunk 开始下一组。
3. 单个 Chunk 超过预算时：
   - `chunker_name == "adaptive_hierarchical"`：抛出不可重试的 `QA_PROVENANCE_CONTRACT_INVALID`，保留当前行为；
   - legacy parser：使用 `LocalTokenCounter.split_text()` 生成多个虚拟输入片段，但每片必须保留相同 `chunkIndex`、pageNo 和源哈希；若无法安全拆分则失败，不允许静默截断原文。
4. Batch 的 `input_hash` 使用排序后的 `(chunkIndex, content hash, prompt version)`，不保存正文。
5. 保留 `QA_SPLIT_MAX_BATCH_CHARS` 作为没有 tokenizer 时的兼容 fallback，并记录 `budget_mode="chars_fallback"`。

### 约束

- 不得重新编号 `chunkIndex`。
- 不得改变 `_replace_qa_pairs()` 的输出顺序。
- 不得让一个 QA Batch 混入不同 Chunk generation。
- `max_input_tokens <= 0`、`reserved_output_tokens < 0` 立即返回配置错误。
- Prompt 版本变化必须改变 input hash，使旧 checkpoint 失效。

### 测试和验证

```powershell
pytest server/tests/test_qa_split_task.py server/tests/test_batching_pipeline.py server/tests/test_chunk_tokenizer.py -q
```

覆盖：

1. 标题和 schema 固定开销被计入。
2. 一个超大 Chunk 的行为稳定。
3. 批次顺序、chunkIndex 和 input hash 稳定。
4. 二分后的两个 Batch 合并后覆盖集合与原 Batch 相同。
5. 无 tokenizer 时字符 fallback 可运行并带诊断标记。

**Done when**

- QA Service 不再直接用 `len(content)` 决定正常批次边界。
- 所有 Batch 都有预算、索引、输入 hash 和源 Chunk 列表。
- 长 Prompt 在达到模型上下文预算前被拆分。

## Task 5: 批次级 retry、超时二分和错误分类

**实现目标和功能：** 单个 QA Batch 失败时只重试该 Batch；推理 timeout 重试仍失败后自动二分；结构错误和鉴权错误快速终止，不把整个文档重复调用多次。

**Files:**
- Modify: `server/app/services/qa_split_batching.py`
- Modify: `server/app/services/qa_split_service.py`
- Modify: `server/app/tasks/qa_tasks.py`
- Modify: `server/app/core/config.py`
- Test: `server/tests/test_qa_split_task.py`
- Test: `server/tests/test_batching_pipeline.py`

### 类型和函数契约

```python
RETRYABLE_QA_CODES = frozenset({
    "PROVIDER_CONNECTION_TIMEOUT",
    "PROVIDER_WRITE_TIMEOUT",
    "PROVIDER_POOL_TIMEOUT",
    "PROVIDER_INFERENCE_TIMEOUT",
    "PROVIDER_OVERALL_TIMEOUT",
    "PROVIDER_CONNECTION_ERROR",
    "PROVIDER_RATE_LIMITED",
    "PROVIDER_SERVER_ERROR",
})

TERMINAL_QA_CODES = frozenset({
    "QA_PROVENANCE_CONTRACT_INVALID",
    "QA_SPLIT_INVALID_OUTPUT",
    "QA_SPLIT_MODEL_NOT_CONFIGURED",
    "QA_PROVENANCE_UNKNOWN_CHUNK_INDEX",
    "PROVIDER_UNAUTHORIZED",
    "PROVIDER_REQUEST_ERROR",
    "PROVIDER_OUTPUT_TRUNCATED",
})

def execute_qa_batch_with_retry(
    adapter,
    batch: QaBatch,
    *,
    max_retries: int,
    max_split_depth: int,
) -> QaBatchResult: ...
```

### 执行规则

```text
Batch B
  -> 第 0 次调用
  -> retryable error
       -> 指数退避（0.5s、1s，封顶 8s），不超过 max_retries
       -> 仍失败且是 timeout/输出过大
            -> depth < maxSplitDepth 时 split(B) 为 B.left、B.right
            -> 两个子批次独立执行
       -> depth 达上限
            -> 记录失败 Batch 和错误上下文
  -> terminal error
       -> 立即结束当前 Run，不 retry
```

1. 二分点按 Chunk 数量取中点；只有一个 Chunk 的 Batch 不再二分。
2. 子 Batch 的 `parent_batch_id`、`split_depth`、`batch_index_path` 必须保存。
3. 合并结果按原始 Batch 顺序和 `chunkIndex` 排序，不按模型返回顺序盲拼。
4. 一个子批次失败，Run 不得发布任何 ACTIVE `QaPair`。
5. Celery 的 `max_retries=3` 仍保留，但 Celery retry 只用于 Worker/数据库级异常或整个 Run 的可恢复失败；不能在 Batch 内 retry 后又无条件重复所有成功 Batch。

### 错误规则

- `QA_PROVENANCE_CONTRACT_INVALID` 不能调用 `execute_qa_batch_with_retry()` 的网络 retry 分支。
- `PROVIDER_OUTPUT_TRUNCATED` 可以先降低 Batch 规模并二分一次，但不得对同一规模无限重试。
- `429` 使用 `Retry-After`，无效或过大时封顶 30 秒。
- overall timeout 后不得继续使用相同 Batch 和相同并发无条件重放。

### 测试和验证

```powershell
pytest server/tests/test_qa_split_task.py server/tests/test_batching_pipeline.py -q
```

测试场景：

1. 第 1 次 timeout、第 2 次成功：只调用同一 Batch 两次。
2. 原 Batch 两次 timeout，二分后两个子 Batch 成功：最终 QA pair 数和顺序正确。
3. `items` 为 object：只调用一次，错误为 `QA_PROVENANCE_CONTRACT_INVALID`。
4. 401：不 retry。
5. 429：读取 Retry-After 并受上限约束。
6. 单 Chunk timeout：不发生空 Batch 或无限递归。

### 验收证据

- ModelCallLog/TaskRun 中能看到 `retry_count`、`split_depth`、失败 Batch index。
- terminal error 的调用次数等于 1，不超过配置上限。
- provenance failure 不会触发“网络连接失败”提示。

**Done when**

- 一个 Batch 失败不会重新调用之前已成功的 Batch。
- timeout 后能有限二分并恢复长文档处理。
- 所有 retry/split 都受明确上限控制。

## Task 6: 并发上限、动态背压和 Provider 级隔离

**实现目标和功能：** 本地 Ollama 默认低并发，云 Provider 按配置并发；遇到 429、503、timeout 时降低当前 Run 并发，连续成功后缓慢恢复，避免所有 Batch 同时压垮 Provider。

**Files:**
- Modify: `server/app/services/_batching.py`
- Create: `server/app/services/qa_split_backpressure.py`
- Modify: `server/app/services/qa_split_service.py`
- Modify: `server/app/core/config.py`
- Test: `server/tests/test_batching_pipeline.py`
- Test: `server/tests/test_qa_split_task.py`

### API 契约

```python
@dataclass
class BackpressureState:
    current_concurrency: int
    min_concurrency: int
    max_concurrency: int
    consecutive_successes: int = 0

    def on_retryable_failure(self, code: str) -> int: ...
    def on_success(self) -> int: ...

def run_ordered_with_backpressure(
    items: Sequence[T],
    worker: Callable[[T], R],
    state: BackpressureState,
) -> list[R]: ...
```

### 调度规则

1. 初始并发：
   - `OLLAMA` 默认 1；
   - OpenAI-compatible/Claude 默认取配置值，最大不超过 `QA_SPLIT_MAX_CONCURRENCY`；
   - Provider config 中显式 `qaSplit.maxConcurrency` 优先，但不得超过系统上限。
2. 收到 `429`、`503`、`PROVIDER_INFERENCE_TIMEOUT`、`PROVIDER_OVERALL_TIMEOUT`：
   - 当前并发减半，最小为 1；
   - 暂停一个退避窗口；
   - 后续 Batch 使用新并发。
3. 连续 3 个成功 Batch：
   - 当前并发加 1；
   - 不超过最大值。
4. 单个 Run 的状态不能影响其他 tenant 的 Run；进程内共享状态必须按 `provider_id + model_config_id` 隔离。
5. `run_ordered()` 保持现有签名和有序返回，用新函数承载需要背压的 QA 路径，Embedding 继续使用既有静态并发。

### 边界和约束

- 不在 Worker 线程中操作 SQLAlchemy Session。
- 不允许通过创建无限线程池来实现动态并发。
- provider rate limit 降载不能修改全局 Settings。
- `maxConcurrency=0` 按 1 处理或在配置层拒绝，不能产生空执行。

### 测试和验证

```powershell
pytest server/tests/test_batching_pipeline.py server/tests/test_qa_split_task.py -q
```

必须验证：

1. 失败后并发从 4 降到 2、再到 1。
2. 连续成功 3 次只恢复 1 级。
3. 不同 Provider 的状态互不影响。
4. 返回顺序与输入顺序一致。

**Done when**

- Ollama QA 默认不再以 4 并发压测。
- 429/5xx/timeout 会触发有上限的背压。
- 现有 `run_ordered()` 测试和 Embedding 行为不变。

## Task 7: 新增 QA Split Run/Batch 数据模型和 Alembic migration

**实现目标和功能：** 为长文档 QA 建立可查询的 Run 和 Batch 状态，保存 checkpoint 所需的最小元数据，不把完整 Prompt/模型输出写入数据库。

**Files:**
- Create: `server/app/models/qa_split_run.py`
- Modify: `server/app/models/__init__.py`
- Modify: `server/app/db/base.py`
- Create: `server/app/db/migrations/versions/0008_qa_split_long_running.py`
- Create: `server/tests/test_qa_split_run.py`

### ORM 数据模型

`QaSplitRun`：

```text
id: String(36), primary key
tenant_id: String(36), not null
job_id: String(36), unique per active run
document_id: String(36), not null
task_run_id: String(36), nullable
model_config_id: String(36), not null
provider_id: String(36), not null
model_name: String(160), not null
prompt_version: String(80), not null
chunk_generation_hash: String(128), not null
status: CREATED/RUNNING/FAILED/COMPLETED/CANCELLED
batch_count: Integer, not null
completed_batch_count: Integer, default 0
error_code: String(120), nullable
error_message: Text, nullable
created_at/updated_at
```

`QaSplitBatch`：

```text
id: String(36), primary key
run_id: String(36), foreign key, not null
batch_index: String(80), not null
parent_batch_id: String(36), nullable
split_depth: Integer, default 0
chunk_indexes: JSON, not null
input_hash: String(128), not null
estimated_input_tokens: Integer, not null
reserved_output_tokens: Integer, not null
status: PENDING/RUNNING/SUCCESS/FAILED
attempt_count: Integer, default 0
result_payload: JSON, nullable
result_hash: String(128), nullable
error_code: String(120), nullable
error_message: Text, nullable
latency_ms: Integer, nullable
timeout_phase: String(40), nullable
created_at/updated_at
```

### 数据约束

- `result_payload` 只能保存经过 `validate_qa_split_output()` 的最小结构化结果，不保存原始 Prompt。
- `chunk_indexes` 必须唯一、非空且按原始顺序；`batch_index` 使用 `0`, `1`, `0.0`, `0.1` 等稳定路径。
- `(run_id, batch_index)` 唯一。
- 一个 Job 同时只能有一个 `RUNNING` Run；PostgreSQL 使用部分唯一索引，SQLite 测试通过 service 层锁和唯一约束模拟。
- 删除 Document/ImportJob 时 Run/Batch 级联或软删除策略必须与现有 `deleted_at` 约定一致。

### Migration

`0008_qa_split_long_running.py` 必须：

1. 创建 `qa_split_runs`、`qa_split_batches`。
2. 给 `model_configs` 增加四个 timeout 列。
3. 给 `model_call_logs` 增加 Task 10 所需字段；如果 Task 10 与本任务分开提交，migration 仍必须保持单一线性 revision。
4. 对 PostgreSQL 创建：

```sql
CREATE UNIQUE INDEX uq_qa_split_run_running_job
ON qa_split_runs(job_id)
WHERE status IN ('CREATED', 'RUNNING');
```

5. downgrade 删除新表和新增字段，不删除已有业务数据。

### 测试和验证

```powershell
alembic upgrade head
pytest server/tests/test_qa_split_run.py -q
```

测试：

1. Run/Batch 能创建、更新、查询。
2. `(run_id, batch_index)` 重复被拒绝。
3. migration upgrade/downgrade 在 SQLite 和 PostgreSQL CI 语法下可执行。
4. `result_payload` 不包含 `prompt`、`api_key`、`content` 原文键。

**Done when**

- 新数据库能通过 `alembic upgrade head`。
- 旧数据库升级不改写已有 QA pair 状态。
- Run/Batch 可以表达 pending、success、failed、split child 和错误信息。

## Task 8: checkpoint 恢复和最终一次性发布

**实现目标和功能：** 重启 Worker 或 Celery retry 后从未完成 Batch 继续，不重复已成功 Batch；只有完整 Run 通过 provenance 校验后才删除旧 QA pair 并创建新的 ACTIVE QA pair。

**Files:**
- Create: `server/app/services/qa_split_run_service.py`
- Create: `server/app/schemas/qa_split_run.py`
- Modify: `server/app/services/qa_split_service.py`
- Modify: `server/app/tasks/qa_tasks.py`
- Modify: `server/app/services/embedding_service.py`
- Test: `server/tests/test_qa_split_run.py`
- Test: `server/tests/test_qa_split_task.py`
- Test: `server/tests/test_embedding_task.py`

### 服务 API

```python
class QaSplitRunService:
    def get_or_create_run(
        self,
        *,
        job: ImportJob,
        document: Document,
        model_config: ModelConfig,
        provider: ModelProvider,
        batches: list[QaBatch],
        task_run_id: str | None,
    ) -> QaSplitRun: ...

    def claim_next_pending_batch(self, run_id: str) -> QaSplitBatch | None: ...

    def save_success(
        self,
        batch_id: str,
        validated_items: list[ValidatedQaItem],
        *,
        latency_ms: int,
    ) -> None: ...

    def save_failure(
        self,
        batch_id: str,
        *,
        code: str,
        message: str,
        retryable: bool,
        timeout_phase: str | None,
    ) -> None: ...

    def collect_complete_items(self, run_id: str) -> list[ValidatedQaItem]: ...

    def publish_complete_run(
        self,
        run_id: str,
        *,
        job: ImportJob,
        document: Document,
        chunks: list[DocumentChunk],
    ) -> list[ValidatedQaItem]: ...
```

### 运行顺序

```text
读取当前 Chunk generation
  -> 计算 batches 和 run fingerprint
  -> get_or_create_run()
  -> 只选 PENDING/FAILED 且允许重试的 Batch
  -> 成功后事务保存 validated result
  -> Worker 中断后重新进入，只 claim 未完成 Batch
  -> 全部 SUCCESS
  -> collect_complete_items()
  -> 对完整结果再次执行 provenance 覆盖校验
  -> publish_complete_run()
      -> _replace_qa_pairs()
      -> 绑定 embedding run_config_hash
      -> Document.status = EMBEDDING
```

### 发布事务约束

1. 任何 Batch SUCCESS 不得单独创建 ACTIVE `QaPair`。
2. `publish_complete_run()` 必须检查：
   - Run 的 ModelConfig、Provider、model name、prompt version 和 Chunk generation 未变化；
   - Batch 数量和 chunk index union 完整；
   - 没有 `PENDING/RUNNING/FAILED` Batch；
   - 每个 Batch 的结果已通过 validator；
   - 当前文档仍属于同一 ImportJob。
3. 发布事务中才执行 `_replace_qa_pairs()`；发布成功后将 Run 标记 `COMPLETED`。
4. 发布失败必须 rollback，旧 ACTIVE QA pair 不得被删除。
5. `EmbeddingService._list_qa_pairs()` 增加测试断言：它只能读取已发布 ACTIVE/EMBEDDING_FAILED QA pair，不能读取 Run 临时结果。
6. ModelConfig 或 Provider 在 Run 中途变化时，标记 Run `CANCELLED`，创建新 Run，不混用两个模型输出。

### Celery 改动

`split_document_qa_task()` 继续接受：

```python
split_document_qa_task(self, job_id: str, *, enqueue_embedding: bool = True)
```

新增行为：

- service 返回可恢复失败时，`handle_failure()` 只触发 Celery retry；
- retry 再次进入 service 时从 Run/Batch 状态恢复；
- 已有 `TaskRun` 与新 Run 通过 `task_run_id` 关联；
- 旧任务如果没有 Run，自动创建初始 Run。

### 测试和验证

```powershell
pytest server/tests/test_qa_split_run.py server/tests/test_qa_split_task.py server/tests/test_embedding_task.py -q
```

必须覆盖：

1. 第 2/5 个 Batch 成功后进程中断，恢复时只调用剩余 Batch。
2. 全部 Batch 成功后一次性创建全部 QA pair。
3. 一个 Batch 失败时数据库中不存在新的 ACTIVE QA pair。
4. provenance 不完整时发布被拒绝，旧 QA pair 保持原样。
5. Embedding 任务不能读取 PENDING Run 结果。
6. 模型配置变化会使旧 Run 失效。

### 验收证据

- 数据库查询截图或 JSON：Run 状态、Batch 完成数、失败 Batch、恢复后的调用次数。
- `QaPair` 查询证明发布前数量不变，发布后一次性变为完整集合。
- Document 状态路径为 `QA_SPLITTING -> EMBEDDING -> READY`，没有中间未完成 QA 被 Embedding。

**Done when**

- Worker/Celery 重试可以从 checkpoint 继续。
- QA 结果只能通过完整 Run 一次性发布。
- Embedding 永远看不到未完成 Run 的临时结果。

## Task 9: Ollama、OpenAI-compatible、DeepSeek 参数白名单

**实现目标和功能：** 让不同 Provider 使用自己的合法参数，同时避免把未知 `thinking`、`response_format`、`keep_alive` 字段发送给不支持的 API。

**Files:**
- Modify: `server/app/integrations/model_providers/ollama.py`
- Modify: `server/app/integrations/model_providers/openai_compatible.py`
- Modify: `server/app/integrations/model_providers/claude.py`
- Modify: `server/app/integrations/model_providers/registry.py`
- Modify: `server/app/services/model_config_service.py`
- Test: `server/tests/test_model_providers_http.py`
- Test: `server/tests/test_openai_compatible_api.py`
- Test: `server/tests/test_model_config.py`

### 配置白名单

```json
{
  "providerOptions": {
    "OLLAMA": {
      "keepAlive": "10m",
      "numCtx": 8192,
      "numPredict": 4096,
      "temperature": 0
    },
    "OPENAI_COMPATIBLE": {
      "responseFormat": "json_object",
      "reasoningEffort": "low",
      "thinking": false,
      "chatPath": "/chat/completions",
      "embeddingPath": "/embeddings"
    }
  }
}
```

实际落库仍可使用当前 `ModelProvider.config` 与 `ModelConfig.config` JSON，但 service 必须先按 Provider 类型过滤：

```python
ALLOWED_PROVIDER_OPTIONS = {
    "OLLAMA": frozenset({"keepAlive", "numCtx", "numPredict", "temperature"}),
    "OPENAI_COMPATIBLE": frozenset(
        {"responseFormat", "reasoningEffort", "thinking", "chatPath", "embeddingPath"}
    ),
}
```

### Provider 行为

1. Ollama：
   - `/api/chat` 使用实际 `model_name`；
   - `format` 继续使用 QA schema；
   - `options.num_predict` 从 `maxTokens` 或 `numPredict` 得到；
   - `keep_alive` 仅在配置时发送；
   - `test_model_connection()` 仍调用选定模型的 `/api/chat`，不能只调用 `/api/tags`。
2. OpenAI-compatible：
   - DeepSeek 等模型默认使用 `/chat/completions`；
   - `response_format` 只有 `responseFormat=json_object` 或 Provider 能力确认支持时发送；
   - `thinking`、`reasoning_effort` 只能映射到白名单字段；
   - `max_tokens` 必须保留，避免 JSON 输出无限增长；
   - DeepSeek 返回 `finish_reason=length` 时走 Task 3 的截断错误。
3. Claude：
   - 不发送 OpenAI 专属 `response_format`；
   - 保持 `/v1/messages` 和既有 headers。

### 约束

- 未知参数不得透传。
- API Key 不得出现在配置回显或 ModelCallLog。
- DeepSeek 只是 OpenAI-compatible 的一个配置实例，不新增硬编码 DeepSeek Provider。
- Provider 不支持 JSON mode 时，QA 仍必须依靠 Prompt + 后端 validator；不能把 JSON mode 失败包装为网络错误。

### 测试和验证

```powershell
pytest server/tests/test_model_providers_http.py server/tests/test_openai_compatible_api.py server/tests/test_model_config.py -q
```

检查 request body：

1. Ollama 请求只包含其允许的 `options`。
2. DeepSeek/OpenAI-compatible 在配置开启时包含 `response_format`，关闭时不包含。
3. Claude 请求无 OpenAI 字段。
4. 未知字段不出现在 HTTP body。

**Done when**

- Ollama、DeepSeek/OpenAI-compatible、Claude 的请求体互不污染。
- 配置页面可以明确知道哪些参数属于哪个 Provider。
- 连接测试和实际 QA 调用使用同一个 model name 与 endpoint。

## Task 10: ModelCallLog 增加批次、输入输出统计和 timeout phase

**实现目标和功能：** 将一次长文档 QA 调用拆成可定位的安全日志，能回答“哪个 Provider、哪个模型、哪个 Batch、哪一阶段超时、重试几次”。

**Files:**
- Modify: `server/app/models/model_config.py`
- Modify: `server/app/services/qa_split_service.py`
- Modify: `server/app/services/model_config_service.py`
- Modify: `server/app/repositories/model_call_log_repo.py`
- Modify: `server/app/services/log_query_service.py`
- Modify: `server/app/schemas/logs.py`
- Modify: `server/app/api/v1/logs.py`
- Modify: `server/app/core/log_redaction.py`
- Test: `server/tests/test_logs_observability.py`
- Test: `server/tests/test_qa_split_task.py`

### 新增字段

```text
ModelCallLog.batch_id: String(36), nullable
ModelCallLog.batch_index: String(80), nullable
ModelCallLog.retry_count: Integer, default 0
ModelCallLog.split_depth: Integer, default 0
ModelCallLog.input_char_count: Integer, nullable
ModelCallLog.estimated_input_tokens: Integer, nullable
ModelCallLog.output_char_count: Integer, nullable
ModelCallLog.estimated_output_tokens: Integer, nullable
ModelCallLog.timeout_phase: String(40), nullable
ModelCallLog.endpoint: Text, nullable
ModelCallLog.model_name_snapshot: String(160), nullable
```

`token_usage` 只允许放供应商返回的数值字段，例如 `prompt_tokens`、`completion_tokens`、`total_tokens`；没有 usage 时保持 `{}`。

### 代码要求

1. `QaSplitService._record_qa_model_call()` 改为接收 `QaBatch` 和 `QaBatchResult`，写入 batch metadata。
2. `ProviderError` 上的 endpoint、model、timeout phase 进入日志快照。
3. `ModelConfigService.test_provider_connection()` 继续记录 `run_id=None`，但保存 model name、endpoint、timeout phase。
4. `ModelCallLogRepository.list_page()` 增加：

```python
batch_id: str | None = None
timeout_phase: str | None = None
provider_id: str | None = None
model_config_id: str | None = None
```

5. `LogQueryService.list_model_calls()` 输出新字段，并通过 `redact_log_payload()` 处理消息。
6. 不输出 `api_key`、Prompt、完整 output、quote 或 PDF 原文。

### 测试和验证

```powershell
pytest server/tests/test_logs_observability.py server/tests/test_qa_split_task.py -q
```

验证：

1. QA 成功日志包含 run_id、batch_id、batch_index、latency 和输入 token 估算。
2. timeout 日志包含 `timeoutPhase=read` 或 `overall`。
3. 错误消息含 Provider/model/endpoint，但不含 API Key 和 Prompt。
4. API 过滤 `runId`、`batchId`、`timeoutPhase` 生效。

**Done when**

- 终端或管理端日志能精确定位到 Provider、模型、endpoint、Batch 和 timeout phase。
- 日志字段不泄漏敏感数据。
- 现有 `/api/v1/logs/model-calls` 的旧字段仍兼容。

## Task 11: Prometheus 指标和动态调参数据

**实现目标和功能：** 以 Provider、模型、Batch 规模和结果类型为维度统计延迟、timeout、retry、split、provenance 失败和背压，不依赖全局平均值猜参数。

**Files:**
- Modify: `server/app/core/metrics.py`
- Modify: `server/app/services/qa_split_service.py`
- Modify: `server/app/services/qa_split_batching.py`
- Modify: `server/app/services/qa_split_backpressure.py`
- Modify: `server/app/services/embedding_service.py`
- Test: `server/tests/test_observability_infra.py`
- Test: `server/tests/test_qa_split_task.py`

### 指标

新增指标及低基数 label：

```text
lingxi_qa_split_batch_total{provider_type,capability,status}
lingxi_qa_split_batch_duration_ms{provider_type,capability}
lingxi_qa_split_timeout_total{provider_type,timeout_phase}
lingxi_qa_split_retry_total{provider_type,error_code}
lingxi_qa_split_batch_split_total{provider_type,reason}
lingxi_qa_split_concurrency{provider_type}
lingxi_qa_split_provenance_failure_total{reason}
lingxi_embedding_batch_timeout_total{provider_type,timeout_phase}
```

禁止使用 tenant_id、document_id、model_name、run_id、batch_id 作为 Prometheus label，避免高基数。

### 具体记录位置

- `QaSplitService._generate_qa_items()`：Batch success/failure/duration。
- `execute_qa_batch_with_retry()`：retry 和 split reason。
- `BackpressureState`：当前并发 gauge。
- `validate_qa_split_output()`：已有 provenance 指标继续保留。
- `EmbeddingService._embed_batch_with_retry()`：只增加 timeout phase 统计，不改变既有重试。

### 测试和验证

```powershell
pytest server/tests/test_observability_infra.py server/tests/test_qa_split_task.py -q
```

检查 `metrics.render_prometheus()`：

1. 成功和失败计数各出现一次。
2. timeout phase 只出现有限枚举值。
3. 输出中不存在 document id、tenant id、model name。
4. counters 在 `metrics.reset()` 后可复现。

**Done when**

- 可以按 Provider 类型和 timeout phase 统计 QA 长耗时问题。
- 指标不会因为文档数量增长而产生无限 label。
- 现有 dashboard 和 `/metrics` endpoint 不回归。

## Task 12: 管理端模型配置、连接测试和日志展示

**实现目标和功能：** 在“模型配置”页面可配置四阶段 timeout 和 QA Split 参数；连接测试和日志页面显示真实 Provider/model/endpoint/timeout phase，避免只显示“模型供应商连接失败”。

**Files:**
- Modify: `web/admin/src/features/model-config/api/modelConfigApi.ts`
- Modify: `web/admin/src/features/model-config/components/CreateModelModal.tsx`
- Modify: `web/admin/src/features/model-config/components/ModelConfigEditModal.tsx`
- Modify: `web/admin/src/features/model-config/pages/ModelConfigPage.tsx`
- Modify: `web/admin/src/features/logs/types.ts`
- Modify: `web/admin/src/features/logs/api/logsApi.ts`
- Modify: `web/admin/src/features/logs/components/LogDetailDrawer.tsx`
- Modify: `web/admin/tests/t18_admin_list_playwright.py`
- Create: `web/admin/tests/t19_qa_split_timeout_playwright.py`

### API 类型

`ModelConfig` 新增：

```ts
connectTimeoutMs: number | null;
writeTimeoutMs: number | null;
readIdleTimeoutMs: number | null;
overallTimeoutMs: number | null;
```

`ModelConfigUpdatePayload` 新增同名可选字段。QA_SPLIT 编辑表单新增：

- 连接超时（毫秒）
- 请求写入超时（毫秒）
- 首 Token/读取空闲超时（毫秒）
- 单次调用总超时（毫秒）
- 最大输出 Tokens
- QA 最大输入 Tokens
- QA 输出预留 Tokens
- QA Batch retry 次数
- QA 最大二分深度

### UI 行为

1. 创建模型时默认填入按 Provider 类型推导的初始值：
   - Ollama：connect 5000、write 30000、read idle 180000、overall 240000；
   - OpenAI-compatible：connect 10000、write 30000、read idle 120000、overall 180000。
2. 保存前校验非负和 overall >= read idle。
3. 连接测试请求继续调用：

```text
POST /api/v1/model-providers/{providerId}/connection-tests
{ "modelConfigId": selectedQaModelId }
```

4. 结果显示：

```text
供应商：Gemma
模型：gemma3
类型：Ollama
endpoint：http://localhost:11434/api/chat
超时：180 秒 · 读取超时
```

5. 日志模型调用详情显示 runId、batchId、batch index、retry count、split depth、输入 token、timeout phase，但不显示 Prompt。
6. 文案中不能把所有 timeout 都写成“连接失败”。

### 测试和验证

```powershell
cd web/admin
npm run lint
npm run build
pytest tests/t19_qa_split_timeout_playwright.py -q
```

Playwright 必须验证：

1. QA_SPLIT 编辑页面可以填写和保存四个 timeout。
2. 非法组合显示表单错误，不发请求。
3. 连接测试失败时显示真实 Provider、model、endpoint、timeout phase。
4. 日志抽屉显示 Batch 诊断但不显示敏感内容。

**Done when**

- 后台可配置和回显新 timeout 参数。
- 用户无需看 Worker 终端即可判断是 Gemma/Ollama 的连接超时还是读取超时。
- 管理端 TypeScript、lint、build 和 Playwright 通过。

## Task 13: 保持 Embedding 的最终发布边界并补充回归保护

**实现目标和功能：** 明确回答 006 中“Embedding 是否会遇到同类 timeout”的工程边界：Embedding 可以 timeout，但只能读取已发布 ACTIVE QA，且既有批次 retry、数量校验、维度校验和最终事务不被 QA checkpoint 破坏。

**Files:**
- Modify: `server/app/services/embedding_service.py`
- Modify: `server/tests/test_embedding_task.py`
- Modify: `server/tests/test_qa_split_run.py`
- Modify: `server/tests/test_task_reliability.py`

### 具体改动

1. 在 `EmbeddingService.embed_import_job()` 开始处增加：

```python
def _assert_qa_split_published(self, job: ImportJob, document: Document) -> None:
    if job.stage != "EMBEDDING":
        raise EmbeddingServiceError(
            "EMBEDDING_QA_NOT_PUBLISHED",
            "QA Split 尚未完成发布，不能开始 Embedding",
            retryable=False,
        )
```

2. `_list_qa_pairs()` 继续只选择 `status in ("ACTIVE", "EMBEDDING_FAILED")`，并补测试确认 Run 临时 JSON 不会被当成 QaPair。
3. 保持现有 `_embed_batch_with_retry()`：
   - Provider timeout 可 retry；
   - 数量不匹配和维度不匹配为终止错误；
   - 只在最终 `_lock_document_for_embedding_commit()` 后写入向量；
   - QA 和 Chunk 两组都成功后才把 Document 设为 READY。
4. Embedding 日志复用 Task 10 的 timeout phase，但不使用 QA 的 `split_depth` 逻辑。
5. 不把 QA Split 的 Chat 模型自动用于 Embedding；`_default_model()` 仍严格按 `ModelCapability.EMBEDDING`。

### 测试和验证

```powershell
pytest server/tests/test_embedding_task.py server/tests/test_qa_split_run.py server/tests/test_task_reliability.py -q
```

必须验证：

1. QA Run 有 pending Batch 时，Embedding 不入队或立即以 `EMBEDDING_QA_NOT_PUBLISHED` 终止。
2. QA 全部发布后，Embedding 仍能按现有流程到 READY。
3. Embedding Provider timeout 只重试 Embedding Batch，不回滚已发布 QA。
4. Embedding 返回数量不匹配/维度不匹配仍保持原错误码。
5. 文档不会在 QA 未发布时变为 READY。

**Done when**

- QA checkpoint 与 Embedding 之间存在明确状态门槛。
- 现有 Embedding 的批处理和事务一致性测试全部通过。
- QA timeout 不会被错误地记录为 Embedding 成功。

## Task 14: 长 PDF 端到端验收、运行手册和证据归档

**实现目标和功能：** 用可重复的慢模型和真实 Provider 验证从上传 PDF 到 READY 的全链路，证明 timeout 治理不是只在单元测试中成立。

**Files:**
- Modify: `server/tests/e2e/test_v1_1_release_e2e.py`
- Create: `web/admin/tests/t19_qa_split_timeout_playwright.py`
- Create: `docs/development/v1.1/acceptance/qa-split-long-running/README.md`
- Create: `docs/development/v1.1/acceptance/qa-split-long-running/task-14-run.json`
- Create: `docs/development/v1.1/acceptance/qa-split-long-running/task-14-model-call-log.json`
- Create: `docs/development/v1.1/acceptance/qa-split-long-running/task-14-screenshot-desktop.png`
- Create: `docs/development/v1.1/acceptance/qa-split-long-running/task-14-screenshot-mobile.png`

### 验收场景

#### 场景 A：短文档正常成功

输入：

```text
2 个 Chunk，QA batch 不触发 split，MockProvider 立即返回合法 items。
```

证据：

- `QaSplitRun.status=COMPLETED`
- 所有 Batch `SUCCESS`
- `QaPair` 数量正确
- Document 进入 `EMBEDDING`
- Embedding 成功后进入 `READY`

#### 场景 B：慢模型首 Token 延迟但在 read idle 内返回

输入：

```text
Mock/fixture Provider 延迟 30 秒返回，readIdle=180000，overall=240000。
```

证据：

- QA 成功；
- `timeout_phase` 为空；
- ModelCallLog latency >= 30000；
- 未发生重复调用成功 Batch。

#### 场景 C：原 Batch timeout，二分后成功

输入：

```text
6 个 Chunk 的原 Batch 在第 1 次调用返回 PROVIDER_INFERENCE_TIMEOUT；
两个 3 Chunk 子批次成功。
```

证据：

- 父 Batch `FAILED` 或 `SPLIT`，两个子 Batch `SUCCESS`；
- 子 Batch 的 chunk index union 等于原始 `[0,1,2,3,4,5]`；
- QA pair 顺序保持原始 Chunk 顺序；
- 只有完整发布后才进入 Embedding。

#### 场景 D：结构错误不重试

输入：

```json
{"items": {}}
```

证据：

- 只产生一次模型调用；
- 错误为 `QA_PROVENANCE_CONTRACT_INVALID`；
- 页面显示“QA 拆分输出 items 必须是数组”；
- 不显示“模型供应商连接失败”；
- 无 ACTIVE QA pair 被删除或新增。

#### 场景 E：真实 Ollama Gemma

前置：

```text
Ollama 服务已启动，ModelConfig capability=QA_SPLIT，
provider_type=OLLAMA，model_name=gemma3，readIdle=180000。
```

证据：

- 连接测试 endpoint 为 `/api/chat`；
- 请求 body 的 model 为 `gemma3`；
- QA ModelCallLog provider/model/endpoint 正确；
- 失败时能区分 connect/read/overall。

#### 场景 F：OpenAI-compatible DeepSeek

前置：

```text
Provider type=OPENAI_COMPATIBLE，
ModelConfig capability=QA_SPLIT，
model_name 为实际 DeepSeek Chat 模型，
base_url 为供应商 API 根地址。
```

证据：

- 使用 `/chat/completions`；
- `response_format` 只在启用且供应商支持时发送；
- 429/5xx 有 retry/backpressure；
- `finish_reason=length` 变为 `PROVIDER_OUTPUT_TRUNCATED`。

### 运行命令

```powershell
pytest server/tests/test_qa_split_run.py server/tests/test_qa_split_task.py server/tests/test_model_providers_http.py server/tests/test_embedding_task.py -q
pytest server/tests/e2e/test_v1_1_release_e2e.py -q
cd web/admin
npm run lint
npm run build
pytest tests/t19_qa_split_timeout_playwright.py -q
```

### 证据要求

`README.md` 必须记录：

```text
测试日期
Git commit
数据库 migration revision
Provider 类型
模型名
四类 timeout
QA batch 数
并发变化
失败/重试/split 次数
最终 Document.status
最终 ImportJob.status
```

不得记录 API Key、完整 Prompt、完整模型输出和 PDF 原文。

**Done when**

- 场景 A-F 均有可复查证据。
- 单元、集成、E2E、管理端构建全部通过。
- 验收证据可以定位 Provider、模型、endpoint、Batch、timeout phase 和最终状态。
- 运行手册明确说明 Ollama/DeepSeek 的初始配置及失败排查顺序。

## 实施顺序、提交边界和回滚

### 推荐顺序

```text
Task 1 配置契约
  -> Task 2 HTTP timeout
  -> Task 3 流式/finish_reason
  -> Task 4 token batching
  -> Task 5 retry/split
  -> Task 6 backpressure
  -> Task 7 migration/model
  -> Task 8 checkpoint/publish
  -> Task 9 provider options
  -> Task 10 logs
  -> Task 11 metrics
  -> Task 12 admin
  -> Task 13 embedding boundary
  -> Task 14 E2E acceptance
```

### 每个提交的最小原则

1. 每个 Task 单独提交，提交前只加入该 Task 的文件。
2. Task 7 migration 必须在 Task 8 使用新表前合入。
3. Task 8 合入前，旧 QA 主流程测试必须继续通过；必要时通过 feature flag 先只启用新的 Run/Batch 路径。
4. Task 12 前端提交必须与对应 API schema 同步。
5. Task 14 不得以“手工看过页面”替代自动测试和 JSON/数据库证据。

### 回滚规则

- 配置回滚：清空新 timeout 字段，旧 `timeoutMs` 继续生效。
- Provider timeout 回滚：保留新错误码解析兼容，但关闭新分阶段 timeout feature flag。
- QA checkpoint 回滚：停止新 Run 创建，已有 Run 标记 `CANCELLED`，通过新的 QA 任务重新生成；不得直接把临时结果发布为 ACTIVE。
- 数据库回滚：只允许在没有新 Run/Batch 生产数据或已完成数据迁移时执行 downgrade；生产环境优先 forward fix，不用 downgrade 删除表。

## 最终整体验收清单

- [ ] `QA_SPLIT_MAX_BATCH_CHARS` 只作为兼容 fallback，正常路径使用 token budget。
- [ ] Ollama 默认并发为 1，云 Provider 并发可配置且有上限。
- [ ] `connect/write/read-idle/overall` 四类 timeout 可配置并被实际 adapter 使用。
- [ ] 连接超时、写入超时、读取超时、整体超时错误码不同。
- [ ] 错误信息至少包含 Provider、模型、endpoint、超时秒数和 timeout phase。
- [ ] timeout 可有限 retry，超时大 Batch 可二分，不会无限循环。
- [ ] provenance/JSON/鉴权错误不会被当作网络错误重试。
- [ ] Batch checkpoint 能恢复，成功 Batch 不重复调用。
- [ ] 未完成 Run 不产生 ACTIVE `QaPair`，Embedding 不读取临时结果。
- [ ] 所有 QA Batch 完成且 provenance 校验通过后才一次性发布。
- [ ] Embedding 仍保持数量、维度、generation 和最终事务保护。
- [ ] ModelCallLog、Prometheus、管理端日志能定位 Provider、模型、endpoint、Batch 和 phase。
- [ ] 不泄露 API Key、Prompt、完整模型输出和 PDF 敏感正文。
- [ ] Ollama Gemma、OpenAI-compatible DeepSeek、MockProvider 三类路径均有测试。
- [ ] 单元、集成、E2E、前端 lint/build/Playwright 全部通过。

## 计划自审结果

### 对 005 的覆盖

005 的 L1-L7 均已映射到 Task 1-12；006 中关于 DeepSeek、Chunk、Embedding 的边界分别落在 Task 9、Task 4 和 Task 13；此前 `QA_PROVENANCE_CONTRACT_INVALID` 的修复要求在 Task 5、Task 8、Task 14 中作为不可误重试和最终发布前校验处理。

### 占位符检查

本文不使用未定义的占位任务或未明确的未来工作作为实施步骤。每个任务均给出具体文件、函数/API 名称、数据结构、测试命令、证据和 `Done when`。

### 类型和接口一致性

- `ProviderTimeouts` 由 Task 2 定义，Task 3、Task 9 使用。
- `QaBatch` 由 Task 4 定义，Task 5、Task 7、Task 8、Task 10 使用。
- `QaSplitRunService` 由 Task 8 定义，Task 7 提供其持久化表，Task 14 验收。
- `ModelCallLog` 新字段由 Task 10 统一定义，Task 11 指标只引用有限枚举字段。
- Embedding 不复用 QA 的 split/retry 语义，只复用 Provider timeout 错误 contract 和最终发布状态门槛。
