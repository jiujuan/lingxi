# 灵犀（Lingxi）RAG 知识库 — 可执行 Issue 列表

> 来源：`arch-analysis.md`
> 版本：v1.1 ｜ 生成日期：2026-07-05
> 说明：每个 Issue 可直接录入 GitHub/GitLab。字段含义——
> **优先级** P0 阻断 / P1 架构债 / P2 质量 ｜ **标签** 便于分类过滤 ｜ **依赖** 需先完成的 Issue ｜ **估时** 粗略人日（1 人）

---

## 里程碑规划

| 里程碑 | 目标 | 包含 Issue |
|---|---|---|
| **M1 — 让系统真的能用** | 真实模型 + 真检索 + 密钥安全 | #1 #2 #3 #4 |
| **M2 — 后端可靠性底座** | 任务重试/幂等、连接池、SSE、鉴权 | #5 #6 #7 #8 #9 #10 |
| **M3 — 前端上线就绪** | 部署、401/RBAC、请求层、类型、SSE | #11 #12 #13 #14 #15 |
| **M4 — 持续重构** | 可观测性、DI、组件、样式、CI | #16 #17 #18 #19 #20 #21 #22 |

## 进展跟踪

| Issue | 状态 | 说明 |
|---|---|---|
| #1 真实 Provider | ✅ 已完成（2026-07-06） | httpx 实现 openai_compatible / ollama / claude / internal_gateway；`HttpProvider` 统一超时+重试(指数退避)+错误映射；mock 抽为 `MockProvider` 由 registry 按 `mock://`/fixture 标记分发；新增 `test_model_providers_http.py`（httpx MockTransport 打桩）。 |
| #2 检索下推 | ✅ 已完成（2026-07-06） | `RetrievalRepository` 方言感知：PostgreSQL 走 pgvector `<=>`+HNSW 与 `to_tsquery`/`ts_rank`（GIN，jieba 分词），DB 内取 top-k；SQLite 保留 Python 兜底（测试用）。修复查询期 `api_key=None` bug。**遗留**：`has_answer` 阈值重标定与 1万+QA P95 基准需真实 PG 环境 → 归入 #20。 |
| #3 密钥 fail-fast | ✅ 已完成（2026-07-06） | 取消加密密钥→JWT 密钥的静默回退，两把密钥各自独立 dev 默认值；新增 `validate_secret_config`：生产环境校验两把密钥均已设置、≥32 字符、且互不相同，否则抛 `ConfigurationError` 拒绝启动；接入 `create_app()` 与 `celery_app` 启动期；`.env.example` 拆分两键并附生成命令。 |
| #5 任务重试/幂等 | ✅ 已完成（2026-07-06） | Celery 任务改 `bind=True`+`acks_late=True`+`max_retries`，失败时经 `handle_failure` 真正抛异常（可重试则 `self.retry`+指数退避，否则终态 `TaskProcessingError`），retryable 由持久化 `TaskRun.error` 读取；`enqueue_*` 不再静默 `return False`（log+raise），API 路径入队失败标记 job FAILED(retryable) 并返回 503；三个 service 的 `except` 加 `logger.exception` 保留堆栈；COMPLETED 任务重复投递短路（幂等）。新增 `test_task_reliability.py`；全量 90 passed。 |
| #6 分批处理 | ✅ 已完成（2026-07-06） | QA 拆分按字符预算（token 代理）将 chunk 分组、逐组生成再合并（chunk 全局 index 保序）；Embedding 按 `EMBEDDING_BATCH_SIZE` 分批，批内瞬时失败按 `EMBEDDING_BATCH_MAX_RETRIES` 重试、彻底失败交由任务层重跑；两者经 `_batching.run_ordered` 支持有界并发（DB 写仍在主线程，Session 不并发）。新增 5 项配置 + `.env.example`；新增 `test_batching_pipeline.py`；全量 95 passed。 |
| #7 连接池 | ✅ 已完成（2026-07-06） | `db/session.py` 显式配置 `pool_size/max_overflow/pool_recycle/pool_timeout/pool_pre_ping`（`build_db_engine_options`，全部环境变量可覆盖）；API 与 Celery worker 按 `DB_ROLE` 分离，worker 进程启动即 `DB_ROLE=worker` 并可用 `WORKER_DB_*` 独立调参；SQLite 走默认池（不传 QueuePool 参数）。async SQLAlchemy 评估后暂缓（现有同步栈 + 同步 Celery worker，迁移成本大）。新增 4 项配置测试；全量 99 passed。 |
| #8 SSE 校验前移+心跳 | ✅ 已完成（2026-07-06） | `stream_message_run` 拆为「同步前置校验 + 返回生成器」，会话不存在/空消息在 StreamingResponse 发 200 前正确返回 404/400；新增 `SseService.stream_with_heartbeat`：源生成器在后台线程跑，主线程在静默超过 `SSE_HEARTBEAT_SECONDS` 时注入 `: heartbeat` 注释帧（仅 worker 线程持有 Session，无并发访问），异常回传主线程。新增 4 项 SSE 测试；全量 103 passed。 |
| #9 JWT 可吊销 | ✅ 已完成（2026-07-06） | User 新增 `token_version`（迁移 0002），token 内嵌 `ver`；`assert_token_current` 在鉴权与 refresh 时比对，登出（`AuthService.logout`）/改密/禁用调 `revoke_tokens` 自增版本即刻吊销所有已签发 token；`decode_token` 校验 `iss`/`aud`；refresh 默认收紧至 14 天。新增 2 项测试（登出吊销 access+refresh、错误 aud 拒绝）；全量 105 passed。 |
| #10 AEAD 加密+迁移 | ✅ 已完成（2026-07-06） | `secrets.py` 换用 `cryptography` 的 **AES-256-GCM**（`enc:v2`，随机 nonce），保留 `enc:v1` 兼容解密（读旧写新）；`encrypt/decrypt` 支持 `secret_key` 参数以支持轮换。新增 `scripts/reencrypt_secrets.py`（格式迁移 + 密钥轮换，`OLD_SECRET_ENCRYPTION_KEY`）与轮换文档；`env.py` 开 `compare_type/compare_server_default`，0001 作 baseline、后续增量 autogenerate。`requirements` 加 `cryptography`。新增 `test_secrets_crypto.py`（6 项）；全量 111 passed。 |
| #11 前端 401/RBAC | ✅ 已完成（2026-07-06） | `apiRequest` 归一化 `ApiError`（保留 code/requestId、兼容非 JSON/网络错误），带 token 的 401 → `clearAuth`+跳登录（登录请求 `skipAuthRedirect` 避免回环）；`authStore` 增 `clearAuth/getToken/hasPermission/redirectToLogin`，`currentUser` 解析加 try/catch 防脏数据白屏；`routes` 按 `user.permissions` 过滤菜单/路由并给无权兜底页；`PermissionGate` 接线到文档删除/权限/重试与日志任务重试等敏感操作。`vite build` 通过（66 模块）。 |
| #12 TanStack Query | ✅ 已完成（2026-07-06） | 引入 `@tanstack/react-query`（装进 `web/admin`），`main.tsx` 挂 `QueryClientProvider`；`queryClient.ts` 配置：4xx 不重试、瞬时错误重试 1 次、`staleTime 30s`（切页命中缓存）、`queryKeys` 工厂。Dashboard/Settings/ApiKeys/ModelConfig/Logs 迁移到 `useQuery`/`useMutation` + 失效刷新，错误经 `ApiError`/`errorMessage` 展示。Chat（SSE→#14）与 Knowledge（体量大）保留 useState 作后续。`vite build` 通过（114 模块）。 |

---


# M1 — 让系统真的能用（P0）

## Issue #1 — 实现真实模型 Provider（LLM + Embedding）
- **优先级**：P0 ｜ **标签**：`backend` `rag` `blocker` ｜ **来源**：P0-1 ｜ **依赖**：无 ｜ **估时**：4–6d
- **影响文件**：`integrations/model_providers/{claude,ollama,openai_compatible,internal_gateway}.py`、`base.py`、`registry.py`
- **背景**：四个 provider 均为 5 行空子类，继承的 `ConfiguredProvider` 是 mock（`embed_texts` 返回 SHA256 哈希向量、`complete_chat` 返回硬编码字符串）。系统从未真正调用过任何模型。
- **验收标准**：
  - [ ] 每个 provider 用 httpx 真实调用对应 API（chat / stream / embedding）
  - [ ] mock 与真实实现平级实现同一接口，mock 仅用于测试
  - [ ] 统一超时、重试（指数退避）、错误映射到 `openai_errors`
  - [ ] `test_connection` 真实探活
  - [ ] embedding 维度与配置一致（如 1536），与库内向量空间一致
- **任务清单**：
  - [ ] 重构 `base.py`：抽出纯接口 `ChatProvider`/`EmbeddingProvider`，mock 独立成 `MockProvider`
  - [ ] 实现 `claude` / `openai_compatible` / `ollama` / `internal_gateway` 真实调用
  - [ ] 共享 httpx client（连接复用）+ 超时 + 重试
  - [ ] 单测：真实 provider 用 httpx mock 打桩，验证请求构造与错误处理

## Issue #2 — 检索下推到 pgvector + tsvector（废弃内存全量检索）
- **优先级**：P0 ｜ **标签**：`backend` `rag` `performance` `blocker` ｜ **来源**：P0-2 P0-3 ｜ **依赖**：#1 ｜ **估时**：5–7d
- **影响文件**：`services/retrieval_service.py`、`repositories/document_repo.py`、`repositories/retrieval_repo.py`、迁移 `0001`
- **背景**：每次问答全量拉 QA 进内存用 Python 算余弦；HNSW/tsvector/GIN 索引从不被使用；“BM25” 是字符级 Jaccard；`has_answer` 阈值近乎只认子串精确匹配。O(N) 随数据线性恶化。
- **验收标准**：
  - [ ] 向量召回走 SQL `<=>` + HNSW，DB 内取 top-k（不再拉全量进内存）
  - [ ] 全文召回走 `websearch_to_tsquery` + `ts_rank`（中文分词方案确定）
  - [ ] RRF 融合在 DB 或有界结果集上进行
  - [ ] rerank 用真 reranker 或标准 BM25，替换字符重叠启发式
  - [ ] `has_answer` 阈值基于真实相似度重新标定，泛化用例（非子串）能命中
  - [ ] 1 万+ QA 单查询 P95 < 300ms
- **任务清单**：
  - [ ] `retrieval_repo` 新增向量/全文 SQL 查询方法（带租户 + 授权过滤下推）
  - [ ] 删除/重写 `_cosine`、`_text_score` Python 计算
  - [ ] 确认中文全文检索方案（zhparser / jieba 预分词写入 tsvector）
  - [ ] 重标定阈值 + 回归用例集
  - [ ] 基准测试脚本（不同规模 QA 的查询延迟）

## Issue #3 — 密钥 fail-fast + 加密/JWT 密钥职责分离
- **优先级**：P0 ｜ **标签**：`backend` `security` `blocker` ｜ **来源**：P0-4 ｜ **依赖**：无 ｜ **估时**：1–2d
- **影响文件**：`core/config.py:61-66,121-128`、`core/secrets.py`
- **背景**：`jwt_secret_key` / `secret_encryption_key` 默认弱值 `dev-only-change-before-deployment`，且加密密钥回退到 JWT 密钥；未设环境变量仍启动。
- **验收标准**：
  - [ ] 生产环境（`ENV=production`）启动期校验两把密钥均非默认值、且长度达标，否则拒绝启动
  - [ ] 加密密钥与 JWT 密钥独立配置，取消互相回退
  - [ ] `.env.example` 更新说明与生成命令
- **任务清单**：
  - [ ] `config.py` 加启动期校验（fail-fast）
  - [ ] 拆分两把密钥的读取逻辑
  - [ ] 文档：密钥生成与轮换说明

## Issue #4 — 前端 Dockerfile 改生产构建 + 静态托管
- **优先级**：P0 ｜ **标签**：`frontend` `devops` `blocker` ｜ **来源**：P0-5 ｜ **依赖**：无 ｜ **估时**：0.5d
- **影响文件**：`web/admin/Dockerfile`、`deploy/docker-compose.yml`
- **背景**：`CMD ["npm","run","dev"]` 用开发服务器对外服务，`npm install` 未锁版本。
- **验收标准**：
  - [ ] 多阶段构建：`npm ci && npm run build` → nginx 托管 `dist/`
  - [ ] nginx 配置 SPA fallback + 静态资源缓存头 + API 反代
  - [ ] compose 中前端服务指向新镜像
- **任务清单**：
  - [ ] 改写多阶段 Dockerfile
  - [ ] 增加 `nginx.conf`
  - [ ] 验证生产镜像可正常访问

---

# M2 — 后端可靠性底座（P1）

## Issue #5 — Celery 任务真实抛异常 + 自动重试 + 幂等
- **优先级**：P1 ｜ **标签**：`backend` `celery` `reliability` ｜ **来源**：P1-1 P1-2 ｜ **依赖**：无 ｜ **估时**：3–4d
- **影响文件**：`tasks/*.py`、各 service `_mark_failed`、`import_service.py:32-59`、`qa_split_service.py:75`
- **背景**：service 吞异常后 task 正常 return，Celery 收不到异常、`autoretry_for`/`acks_late` 失效；`enqueue_*` 吞连接失败且调用方忽略返回值，流水线静默断裂。
- **验收标准**：
  - [ ] 任务失败时抛异常，`autoretry_for` + `max_retries` + 指数退避生效
  - [ ] `acks_late=True` + 幂等键，防重复投递重复处理
  - [ ] `enqueue_*` 失败必须抛出/告警，不再静默 `return False`
  - [ ] 失败记录含原始堆栈（`logger.exception`）
- **任务清单**：
  - [ ] 重构 `_mark_failed`：记录后重新 `raise`
  - [ ] task 装饰器加 `autoretry_for`/`retry_backoff`/`acks_late`
  - [ ] 幂等键（job_id + stage）去重
  - [ ] `enqueue_*` 移除吞异常逻辑
  - [ ] 测试：重复投递、broker 失败注入

## Issue #6 — 大文档分批 QA 拆分与分批 Embedding
- **优先级**：P1 ｜ **标签**：`backend` `rag` `scalability` ｜ **来源**：P1-3 ｜ **依赖**：#1 ｜ **估时**：2–3d
- **影响文件**：`services/qa_split_service.py`、`services/embedding_service.py`
- **背景**：QA 拆分把整篇所有 chunk 塞进一个 prompt；embedding 一次性 embed 所有 QA。大文档必然超上下文/超批量限制。
- **验收标准**：
  - [ ] QA 拆分按 token 预算分批，带并发上限
  - [ ] embedding 分批（可配 batch_size），失败批次可重试
  - [ ] 大文档（如 200 页）端到端可跑通
- **任务清单**：
  - [ ] chunk 分批策略 + 并发控制
  - [ ] embedding batch 循环 + 部分失败处理
  - [ ] 测试：超大文档用例

## Issue #7 — 数据库连接池显式配置
- **优先级**：P1 ｜ **标签**：`backend` `database` `reliability` ｜ **来源**：P1-4 ｜ **依赖**：无 ｜ **估时**：1d
- **影响文件**：`db/session.py:8`
- **验收标准**：
  - [ ] 显式配置 `pool_size` / `max_overflow` / `pool_recycle` / `pool_timeout`（可环境变量覆盖）
  - [ ] Celery worker 与 API 进程池参数分别可调
  - [ ] 负载下无连接耗尽
- **任务清单**：
  - [ ] 参数化连接池配置
  - [ ] （评估）异步 SQLAlchemy 以适配 SSE 长连接
  - [ ] 并发压测验证

## Issue #8 — SSE 前置校验前移 + 心跳
- **优先级**：P1 ｜ **标签**：`backend` `sse` `bug` ｜ **来源**：P1-6 ｜ **依赖**：无 ｜ **估时**：1–2d
- **影响文件**：`api/v1/chat.py:51`、`services/chat_service.py:59-63`、`services/sse_service.py`
- **背景**：校验在生成器内，报错时 HTTP 头已 200 发出，客户端拿到断裂流而非 404/400；无心跳易被网关掐断。
- **验收标准**：
  - [ ] 会话存在性/空消息校验在开始流式前完成，能正确返回 404/400
  - [ ] 长时间无输出时发送 keep-alive 心跳帧
  - [ ] 检索阶段不长时间阻塞（配合 #2）
- **任务清单**：
  - [ ] 校验逻辑提到端点/生成器首个 yield 前
  - [ ] SSE 心跳注释帧
  - [ ] 测试：不存在会话、空消息、长连接心跳

## Issue #9 — JWT 可吊销（token_version / jti 黑名单）
- **优先级**：P1 ｜ **标签**：`backend` `security` `auth` ｜ **来源**：P1-5 ｜ **依赖**：无 ｜ **估时**：2–3d
- **影响文件**：`core/security.py`、`services/auth_service.py`、用户模型
- **背景**：无 jti/黑名单/版本号，登出/改密/禁用后 token 仍有效；refresh 可无限续签；未校验 iss/aud。
- **验收标准**：
  - [ ] 登出/改密/禁用后，旧 access & refresh token 立即失效（`token_version` 或 jti 黑名单）
  - [ ] refresh 校验撤销状态
  - [ ] `decode_token` 校验 iss/aud
  - [ ] refresh 有效期与续签策略收紧
- **任务清单**：
  - [ ] 用户表加 `token_version`，签发时嵌入、校验时比对
  - [ ] refresh 撤销检查
  - [ ] iss/aud 校验
  - [ ] 测试：登出/改密后旧 token 拒绝

## Issue #10 — 换标准 AEAD 加密 + 可演进迁移
- **优先级**：P1 ｜ **标签**：`backend` `security` `database` ｜ **来源**：P1-7 ｜ **依赖**：无 ｜ **估时**：2–3d
- **影响文件**：`core/secrets.py`、`db/migrations/`
- **背景**：自研 SHA256 类 CTR 流密码替代标准 AEAD；迁移只有一个 `0001` 用 `create_all`/`drop_all`，非增量。
- **验收标准**：
  - [ ] 用 `cryptography` 的 AES-GCM / Fernet 替换自研算法
  - [ ] 支持已有 `enc:v1:` 数据平滑迁移（读旧写新）或提供 re-encrypt 脚本
  - [ ] 迁移改为 autogenerate 增量，`0001` 作为真实 baseline
  - [ ] 密钥轮换方案文档化
- **任务清单**：
  - [ ] 引入 `cryptography`，实现 AEAD encrypt/decrypt
  - [ ] 兼容旧密文解密 + 重加密迁移脚本
  - [ ] 迁移策略修正
  - [ ] 测试：加解密往返、旧密文兼容

---

# M3 — 前端上线就绪（P0-6 + P1）

## Issue #11 — 全局 401/403 拦截 + 前端 RBAC 门控接线
- **优先级**：P0 ｜ **标签**：`frontend` `auth` `rbac` `blocker` ｜ **来源**：P0-6 ｜ **依赖**：无 ｜ **估时**：2–3d
- **影响文件**：`api/client.ts`、`auth/PermissionGate.tsx`、`routes/index.tsx`、各 feature 页面
- **背景**：token 过期后请求静默失败、不登出不跳转；`PermissionGate` 定义但从未使用，菜单/操作按钮对所有登录者一致可见。
- **验收标准**：
  - [ ] `apiRequest` 统一处理 401 → 清 token + 跳转登录
  - [ ] 403 有明确提示
  - [ ] `PermissionGate` 包裹敏感操作按钮（删除、重试、改权限、看 API Key）
  - [ ] 路由/菜单按 `user.permissions` 过滤
- **任务清单**：
  - [ ] client 拦截 401/403
  - [ ] 路由守卫 + 菜单过滤
  - [ ] 逐页接线 PermissionGate

## Issue #12 — 引入 TanStack Query 统一数据层
- **优先级**：P1 ｜ **标签**：`frontend` `architecture` `refactor` ｜ **来源**：P1-8 ｜ **依赖**：#11 ｜ **估时**：3–5d
- **影响文件**：`api/client.ts`、各 feature `api/*.ts` 与 page
- **背景**：raw fetch 无缓存/重试/去重/超时；`throw response.json()` 掩盖非 JSON 错误、丢 requestId。
- **验收标准**：
  - [ ] 引入 TanStack Query，query/mutation 统一管理
  - [ ] 统一错误解析：保留 requestId/errorCode，兼容非 JSON 响应
  - [ ] 401 拦截接入（配合 #11）
  - [ ] 切页命中缓存，减少重复全量拉取
- **任务清单**：
  - [ ] QueryClient + Provider 接入
  - [ ] 改造 `apiRequest` 错误处理
  - [ ] 逐 feature 迁移 useEffect+useState → useQuery

## Issue #13 — 前后端类型 codegen（OpenAPI → TS）
- **优先级**：P1 ｜ **标签**：`frontend` `types` `dx` ｜ **来源**：P1-10 ｜ **依赖**：无 ｜ **估时**：2–3d
- **影响文件**：各 feature `types.ts`、构建脚本
- **背景**：类型全手写与后端 schema 无同步；运行期零校验，字段变更前端编译期无感知。
- **验收标准**：
  - [ ] 由后端 OpenAPI 生成 TS 类型（openapi-typescript / orval）
  - [ ] 生成纳入构建/CI，schema 变更即类型更新
  - [ ] 关键入口加 zod 运行期校验
- **任务清单**：
  - [ ] 后端导出稳定 OpenAPI schema
  - [ ] 配置 codegen 脚本
  - [ ] 替换手写 types，修复类型漂移

## Issue #14 — SSE 支持中断 + 健壮解析
- **优先级**：P1 ｜ **标签**：`frontend` `sse` `bug` `ux` ｜ **来源**：P1-11 ｜ **依赖**：无 ｜ **估时**：1–2d
- **影响文件**：`features/chat/api/chatApi.ts`、`features/chat/pages/ChatPage.tsx`、`ChatComposer.tsx`
- **背景**：无 AbortController（无“停止生成”、切会话不取消、卸载泄漏）；`JSON.parse` 无 try/catch 崩流；只取单行 data 不兼容多行。
- **验收标准**：
  - [ ] AbortController 支持“停止生成”，切会话/卸载时取消
  - [ ] `parseSseBlock` 的 JSON 解析容错，畸形帧不崩流
  - [ ] 兼容多行 `data:` 拼接
  - [ ] 流超时/断开有提示
- **任务清单**：
  - [ ] 接入 AbortController + 停止按钮
  - [ ] 解析加 try/catch + 多行 data
  - [ ] 卸载清理

## Issue #15 — 文件上传改 multipart + 进度
- **优先级**：P1 ｜ **标签**：`frontend` `ux` `performance` ｜ **来源**：P2-8（提级，影响大文件上线）｜ **依赖**：后端上传接口 ｜ **估时**：1–2d
- **影响文件**：`features/knowledge/components/DocumentUploadPanel.tsx`、后端上传端点
- **背景**：文件读成 base64 塞 JSON，内存膨胀 33%、无进度。
- **验收标准**：
  - [ ] 改 `multipart/form-data`（或预签名直传）
  - [ ] 显示上传进度
  - [ ] 保留前端 SHA-256 校验
- **任务清单**：
  - [ ] 前端改 multipart + 进度事件
  - [ ] 后端接收 multipart（如需）

---

# M4 — 持续重构（P2）

## Issue #16 — 后端全局异常兜底 + CORS + lifespan
- **优先级**：P2 ｜ **标签**：`backend` `robustness` ｜ **来源**：P2-1 ｜ **依赖**：无 ｜ **估时**：1d
- **影响文件**：`main.py`
- **验收标准**：
  - [ ] `RequestValidationError` 与未捕获 500 统一走 `error_payload`，不泄漏堆栈
  - [ ] 配置 CORS
  - [ ] lifespan 管理引擎/连接池优雅启停

## Issue #17 — 结构化日志 + Trace + Metrics + 深度健康检查
- **优先级**：P2 ｜ **标签**：`backend` `observability` ｜ **来源**：P2-2 ｜ **依赖**：无 ｜ **估时**：2–3d
- **影响文件**：`core/logging.py`、`core/log_redaction.py`、`main.py`
- **验收标准**：
  - [ ] JSON 结构化日志，request_id 自动注入
  - [ ] OpenTelemetry trace / `/metrics`（Prometheus）
  - [ ] `/health` 探测 DB/Redis
  - [ ] 脱敏增强（值级匹配兜底）

## Issue #18 — 后端数据访问优化（权限缓存 / N+1 / snapshot 瘦身）
- **优先级**：P2 ｜ **标签**：`backend` `performance` ｜ **来源**：P2-3 ｜ **依赖**：无 ｜ **估时**：2d
- **验收标准**：
  - [ ] 权限组装减少每请求查库次数（缓存/JOIN 合并）
  - [ ] citation `_document_title` 消除 N+1（批量取）
  - [ ] `retrieval_snapshot` 瘦身（截断/分表/仅存必要字段）

## Issue #19 — 后端依赖注入彻底化
- **优先级**：P2 ｜ **标签**：`backend` `refactor` `testability` ｜ **来源**：P2-4 ｜ **依赖**：#1 #2 ｜ **估时**：2d
- **验收标准**：
  - [ ] `RerankService` / provider adapter 通过构造注入，可替换可 mock
  - [ ] 消除 service 内部硬 `new`

## Issue #20 — 补齐真实检索层测试（PG 环境）
- **优先级**：P2 ｜ **标签**：`backend` `testing` ｜ **来源**：P2-5 ｜ **依赖**：#2 ｜ **估时**：2–3d
- **背景**：测试用 SQLite 掩盖了 PG 向量层从未被使用。
- **验收标准**：
  - [ ] 检索层测试在真实 PG + pgvector 上运行（testcontainers/CI service）
  - [ ] 覆盖向量召回、全文召回、RRF、阈值回归
  - [ ] 幂等/连接池/provider 失败注入测试

## Issue #21 — 前端构建配置修正（plugin-react / @types / tsconfig）
- **优先级**：P2 ｜ **标签**：`frontend` `build` `dx` ｜ **来源**：P2-6 ｜ **依赖**：无 ｜ **估时**：0.5d
- **验收标准**：
  - [ ] 安装并启用 `@vitejs/plugin-react`（HMR/Fast Refresh）
  - [ ] 补齐 `@types/react`、`@types/react-dom`
  - [ ] `moduleResolution` 改 `Bundler`

## Issue #22 — 前端组件与样式重构 + 工程门禁
- **优先级**：P2 ｜ **标签**：`frontend` `refactor` `quality` ｜ **来源**：P2-7 P2-9 P2-10 ｜ **依赖**：无 ｜ **估时**：3–5d
- **验收标准**：
  - [ ] 拆分 `LogsPage`（抽公共行渲染）、`ChatPage`（抽 `useChatStream` hook）
  - [ ] 建 `shared/ui`，收敛 `formatTime/formatBytes` 等重复工具与组件
  - [ ] 样式作用域方案（CSS Modules / Tailwind），消除全局类名冲突
  - [ ] 接入 ESLint + Prettier + `tsc --noEmit` + CI 门禁
  - [ ] `currentUser()` JSON.parse 加兜底

---

## 依赖关系图（简）

```
#3 密钥 ──┐
#4 部署 ──┤ (独立, 可最先并行)
          │
#1 provider ──> #2 检索 ──> #6 分批 / #19 DI / #20 测试
                     └────> #8 SSE 阻塞缓解
#11 401/RBAC ──> #12 react-query
#13 类型codegen (独立)
#14 SSE中断 (独立)
其余 P1/P2 多为独立项，可穿插并行
```

## 优先级执行建议
1. **立即并行启动**：#3、#4（低成本、无依赖、直接堵住上线风险）
2. **核心攻坚**：#1 → #2（RAG 生死线，串行）
3. **可靠性**：#5、#7、#8、#9（多数独立，可并行）
4. **前端上线**：#11 → #12，#13/#14 并行
5. **持续项**：M4 随迭代穿插
