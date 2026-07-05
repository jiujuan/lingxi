核实无误：四个 provider 确为空壳、密钥用弱默认值、embedding 用 sha256 哈希、检索全量拉取。下面给出综合分析报告。

---
  灵犀（Lingxi）RAG 知识库 — 前后端架构分析与改进清单

##  一、架构总览

  后端（server/）：FastAPI + 同步 SQLAlchemy 2.x + Celery(Redis) + PostgreSQL/pgvector。分层规范教科书级：api → services → repositories → models/schemas →
  integrations，横切关注点收在 core/。RBAC、审计日志、密钥信封加密、SSE 事件模型、日志脱敏都有骨架。

  前端（web/admin/）：React 19 + TypeScript + Vite。feature-based 目录（chat/knowledge/logs/api-keys/dashboard/model-config/settings），容器/展示分层清晰。

  一句话判断："骨架优秀，内脏中空"。工程规范做得相当到位，但三块核心——真实模型接入、真正的向量/全文检索、生产级安全配置——要么是桩、要么是死代码、要么是弱默认值
  。前端则在几乎所有基础设施（路由/状态/请求/UI 库）上"裸奔"。

  下面按 P0（阻断上线/严重安全）→ P1（架构级技术债）→ P2（质量与体验） 分级。

---
##  🔴 P0 — 阻断性问题（不修则系统不可用或存在严重安全风险）

##   后端

- P0-1｜所有真实模型 Provider 是空壳，系统从未调用过任何 LLM/Embedding
    integrations/model_providers/{claude,ollama,openai_compatible,internal_gateway}.py 全是 5 行空子类，继承的 ConfiguredProvider 是测试用 mock：embed_texts 返回
    SHA256 哈希派生向量、complete_chat 返回硬编码字符串、generate_qa_pairs 返回固定模板。整个 RAG 在接入真实模型前完全不可用。
    → 用 httpx 实现真实 provider（含超时/重试/流控），mock 与真实实现平级实现同一接口，而非当基类。

- P0-2｜检索全量拉内存 + 纯 Python 余弦，pgvector/HNSW/tsvector 索引全是死代码
    retrieval_service.py + document_repo.list_authorized_qa_pairs 每次问答把该租户全部授权 QA 拉进内存，再用 Python 循环算 1536 维余弦。迁移 0001 建的 HNSW
    余弦索引、tsvector GIN 全文索引从不被查询使用（全库确认检索路径不含 <=>/to_tsquery）。1 万条 QA 即单查询秒级，随数据线性恶化。
    → 检索下推到 SQL：pgvector <=> + HNSW 做向量召回，websearch_to_tsquery + ts_rank 做全文，DB 内取 top-k。

- P0-3｜"BM25/语义/rerank" 均为字符级启发式，命中率近乎只认子串
    所谓 BM25 是 _text_score 的字符级 Jaccard（无词频/IDF/长度归一）；rerank 是字符重叠加权无交叉编码器；has_answer 阈值（默认 1.35）几乎必须命中
    exact_boost（查询是库内问题子串，+1.2） 才能过关，泛化能力近乎为零。
    → 配合 P0-1/P0-2 重写为真实 embedding 召回 + 真 reranker（或至少标准 BM25）。

- P0-4｜密钥弱默认值 + 静默回退，无 fail-fast
    core/config.py:61-66,121-128：jwt_secret_key 与 secret_encryption_key 都默认 "dev-only-change-before-deployment"，且加密密钥会回退到 JWT
    密钥。未设环境变量系统照常启动，用弱密钥签 JWT、加密 provider API Key。生产漏配即灾难。
    → 生产环境启动期强制校验密钥非默认值，缺失即 fail-fast 拒绝启动；加密密钥与 JWT 密钥职责分离。

##  前端

- P0-5｜Dockerfile 用 npm run dev 跑生产
    web/admin/Dockerfile 的 CMD ["npm","run","dev"] 用开发服务器对外提供服务，且用 npm install 未锁版本。
    → 改为 npm ci && npm run build + nginx 静态托管。

- P0-6｜无 401/403 处理 + RBAC 门控完全未接线
    api/client.ts 全局无 401 处理，token 过期后所有请求静默失败为通用文案、不登出不跳转，用户困死；auth/PermissionGate.tsx
    定义了却从未被使用（全局仅命中自身），routes/index.tsx 静态菜单对所有登录者一致可见——细粒度 RBAC 在 UI 层根本没上线。
    → apiRequest 统一拦截 401→登出跳登录；用 PermissionGate 包裹操作按钮、按 user.permissions 过滤路由/菜单。

---
##  🟠 P1 — 架构级技术债（影响可靠性、可扩展性、可维护性）

##  后端

- P1-1｜Celery 任务吞异常后正常返回，自动重试机制全失效
    tasks/*.py 内 service 的 _mark_failed 用 try/except Exception 捕获所有错误、写库标 FAILED，然后 task 正常 return dict。Celery
    永远收不到异常，acks_late/autoretry_for/max_retries 无从触发，重试只能人工调 API。且 except 广泛丢弃原始堆栈（无 logger.exception），线上难排障。
    → 让任务真正抛异常，用 autoretry_for + acks_late + 幂等键替代"吞异常 + 人工重试"。

- P1-2｜任务流水线静默断裂 + 非幂等
    import_service.py:32-59、qa_split_service.py:75：enqueue_* 用 try/except: return False 吞掉 broker 连接失败，所有调用方忽略返回值，Redis
    抖动即让文档永久卡在中间态无告警。任务用全删重插（_replace_qa_pairs 硬删 QaPair），Celery at-least-once 重复投递会并发删改，且硬删 QaPair 使历史
    QueryCitation.qa_pair_id 悬空（引用溯源断裂）。
    → enqueue 失败需抛出/告警；任务加幂等键；QA 软删或级联保护 citation。

- P1-3｜大文档无批处理，必然超限
    qa_split_service 把整篇文档所有 chunk 塞进一个 prompt；embedding_service 把所有 QA 问题塞进一次 embed_texts。大文档必然超模型上下文/超 embedding 批量上限。
    → 分批切分与分批 embedding，带并发上限。

- P1-4｜数据库连接池未配置
    db/session.py:8 仅 pool_pre_ping=True，未设 pool_size/max_overflow/pool_recycle/pool_timeout。Celery 多 worker + FastAPI 线程池并发下极易连接耗尽。
    → 显式配置连接池参数；评估 async SQLAlchemy 以匹配 SSE 长连接。

- P1-5｜JWT 不可吊销
    core/security.py：无 jti/黑名单/token 版本号，登出/改密/禁用后已签发 token（access 30 分钟、refresh 默认 30 天）仍有效，refresh
    只校验类型可无限续签；decode_token 未校验 iss/aud。
    → 引入 token_version/jti 黑名单，refresh 校验撤销状态。

- P1-6｜SSE 前置校验在生成器内，报错时已发 200
    chat.py:51 + chat_service.py:59-63：stream_message_run 是生成器，not_found/bad_request 只在 StreamingResponse 开始迭代时才抛，此时 HTTP 头已 200
    发出，客户端拿到断裂流而非 404/400。且检索期间秒级 CPU 阻塞线程池、无心跳帧易被网关掐断。
    → 校验前移到端点执行；加 keep-alive 心跳。

- P1-7｜自研加密算法 + 单一 baseline 迁移
    core/secrets.py 用 SHA256 手搓类 CTR 流密码替代标准 AEAD（虽做了 encrypt-then-MAC 但缺审计/密钥轮换）；迁移只有一个 0001 且 upgrade 直接 create_all、downgrade
    drop_all，非可演进迁移。
    → 换 cryptography 的 AES-GCM/Fernet；改用 autogenerate 增量迁移。

## 前端

- P1-8｜无数据请求层（react-query），全程手写 fetch
    api/client.ts 27 行 raw fetch，无缓存/重试/去重/超时，切页 useEffect 重拉全量；throw response.json() 在后端返回非 JSON（502/网关 HTML）时被掩盖成 parse
    error，丢失 requestId/errorCode，与"可追溯排障"定位自相矛盾。
    → 引入 TanStack Query，统一 loading/error/缓存/401 拦截，删大量样板。

- P1-9｜Token 存 localStorage + 状态非响应式
    auth/authStore.ts 只是操作 localStorage 的纯函数（非真 store），accessToken 存 localStorage 是 XSS 窃取面（当前无 dangerouslySetInnerHTML，风险暂可控但"一旦
    XSS 即账号沦陷"）；user/token 非 React state，登录/登出靠 location.reload() 硬刷。
    → 迁 HttpOnly Cookie + CSRF；用真状态管理消除 reload workaround。

- P1-10｜前后端类型全手写、无 codegen、运行期零校验
    各 feature 手写 types.ts，与后端 schema 无同步；apiRequest<T> 是纯断言、SSE data 是 Record<string,unknown> 靠强转兜底。后端字段一变前端编译期无感知。
    → 从后端 OpenAPI 生成类型（openapi-typescript/orval），或入口加 zod 校验。

- P1-11｜SSE 无法中断 + 解析脆弱
    chatApi.streamChatMessage 无 AbortController：无"停止生成"、切会话/卸载流不取消（setState-on-unmounted 泄漏）；parseSseBlock 的 JSON.parse 无
    try/catch，畸形帧崩流；只取单行 data: 不兼容多行 data。
    → 加 AbortController + try/catch + 多行 data 拼接。

---
## 🟡 P2 — 质量与体验优化

## 后端

  - P2-1 缺全局异常兜底：main.py 无 CORS、无 RequestValidationError/500 统一 handler、无 lifespan 优雅关闭，非 HTTPException
    走默认返回体、格式不统一且可能泄漏堆栈。
  - P2-2 可观测性浅：logging.py 仅 basicConfig 文本日志，非结构化 JSON、无 trace/OpenTelemetry/metrics，/health 不探
    DB/Redis；脱敏靠键名启发式（值出现在非敏感键会漏）。
  - P2-3 权限组装每请求 3 次查库无缓存、citation _document_title N+1、retrieval_snapshot 全量落库单行 JSON 巨大。
  - P2-4 DI 不彻底：service 内部硬 new（RerankService()、build_provider_adapter），难 mock 难替换。
  - P2-5 测试用 SQLite（EmbeddingVector 退化为 JSON），恰好掩盖了 PG 向量层从未被使用；真检索质量零覆盖，缺幂等/连接池/provider 失败注入测试。

## 前端

  - P2-6 未装 @vitejs/plugin-react（无 HMR/Fast Refresh），缺 @types/react，moduleResolution: Node 过旧。
  - P2-7 巨型组件：LogsPage（322 行，四份重复行渲染）、ChatPage（15 个 useState 未抽 hook）。
  - P2-8 DocumentUploadPanel 把文件读成 base64 塞 JSON 上传（内存膨胀 33%、无进度），应改 multipart/预签名直传。
  - P2-9 全局 styles.css（1001 行）无作用域，动态类名 status-${x} 靠 CSS 穷举，漏一个掉样式；缺 shared/ui 公共层导致 formatTime/formatBytes 到处重复。
  - P2-10 无 ESLint/prettier/tsc --noEmit/前端单测/CI 门禁；currentUser() 的 JSON.parse 无兜底，脏 localStorage 会白屏。

---
 ##  建议的修复顺序

  1. 先让系统"真的能用"：P0-1（真实 provider）→ P0-2/P0-3（真检索）→ P0-4（密钥 fail-fast）。这三步之前，系统本质是不产出真实答案的 demo。
  2. 再补可靠性底座：P1-1/P1-2（Celery 重试与幂等）、P1-4（连接池）、P1-6（SSE 校验前移）。
  3. 前端并行推进：P0-5/P0-6（部署 + 401/RBAC 接线）→ P1-8（react-query）→ P1-10（类型 codegen）。
  4. P2 作为持续重构项，随功能迭代顺手清理。

  需要的话，我可以针对任一条目（如 P0-2 检索下推到 pgvector 的具体改造、P1-8 react-query 迁移方案、P1-1 Celery 重试改造）直接给出落地代码。

✻ Churned for 8m 44s

※ recap: Analyzed the Lingxi RAG project's frontend and backend architecture and delivered a P0/P1/P2 improvement list. Analysis is complete; next step is to
  implement a specific fix if you pick one, such as pgvector retrieval, Celery retries, or react-query migration. (disable recaps in /config)