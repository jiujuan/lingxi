# 灵犀（Lingxi）文档解析架构设计 —— 可插拔解析器与 MinerU / Docling 集成

> 版本：V1.1
> 日期：2026-07-07（同日追加 §十二 Docling 双引擎）
> 范围：`server/app/integrations/parsers/`、上传校验（`import_service`）、解析任务（`document_parse_service`）、健康检查、前端上传面板
> 关联：[01-technical-architecture.md](./01-technical-architecture.md)、[analysis/llamaindex-comparison.md](./analysis/llamaindex-comparison.md)（本设计落实其"补 PDF 摄取"建议）

---

## 一、目标与非目标

**目标**

1. 把 `parsers/` 重构为**注册表驱动的可插拔解析器架构**：新增一种文件格式 = 新增一个 `ParserAdapter` 子类 + 注册到链上，上传白名单自动跟随；
2. 落地真正的 **MinerU 解析器**：通过 HTTP 调用自部署的 `mineru-api`（MinerU 3.x，原生支持 PDF/DOCX/PPTX/XLSX/PNG/JPG）；
3. 新增**本地 CSV 解析器**（仅 Python 标准库）；
4. 保持既有契约不变：`ParserAdapter.supports()/parse()`、`ParserError(code, message, retryable)`、Celery 按 `TaskRun.error.retryable` 决定重试的机制全部原样保留。

**非目标**

- 不接 MinerU 官方云 API（mineru.net）——客户端形状已为其预留（见 §7），本期不实现；
- 不在进程内 import `mineru` Python 库（torch 等数 GB 依赖会进 worker 镜像）；
- 不做 office 格式的本地轻量解析（python-docx/openpyxl 等），统一交给 MinerU；
- 不改 QA 拆分与嵌入阶段。

## 二、总体架构

```
上传入口（API 进程）                     解析阶段（Celery worker，parse 队列）
┌──────────────────────┐               ┌─────────────────────────────────────┐
│ POST /import-jobs/…/file             │ parse_document_task                  │
│   _validate_file_limits ─────┐       │   DocumentParseService              │
│   （415 / 413）              │       │     get_parser_chain()              │
└──────────────┬───────────────┘       │       ├─ LightweightParser (.md/.txt)│
               │                       │       ├─ CsvParser        (.csv)     │
      allowed_upload_extensions()      │       └─ MinerUParser     (.pdf/…)───┼──HTTP──▶ mineru-api
               │                       │     _select_parser → parse()         │          (自部署)
       parsers/registry.py ◀───────────┤     ParsedDocument                   │
      （上传门与解析链共用一份事实）      │       ├─ markdown → ParseArtifact    │
                                       │       └─ blocks   → DocumentChunk    │
                                       └─────────────────────────────────────┘
```

核心原则：**上传门与解析链共用同一个注册表**。上传门永远不接受解析阶段处理不了的文件——MinerU 未配置时，PDF/Office/图片扩展名根本不出现在白名单里，在入口就被 415 拒绝，而不是入库后解析必败。

## 三、ParserAdapter 契约

```python
class ParserAdapter:
    name: str                                  # 写入 Document.parser_name
    version: str
    extensions: frozenset[str]                 # 小写、带点，如 {".pdf"}
    mime_types: frozenset[str]

    def is_available(self) -> bool: ...        # 依赖服务未配置 → False
    def supports(self, source) -> bool: ...    # 基类默认实现：后缀优先、mime 次之
    def parse(self, request) -> ParsedDocument: ...
```

- `supports()` 后缀优先：客户端上传的 `content_type` 不可信（常见 `application/octet-stream`），mime 只作补充匹配；
- `ParsedDocument.markdown` 存为 `ParseArtifact`（`artifacts/{doc}/parsed.md`），`blocks` 落 `DocumentChunk`；
- `ParserError.retryable` 语义不变：True → Celery 指数退避重试（5s→600s，最多 3 次）；False → 任务终态失败。

### source_locator 的三种形态

| 解析器 | locator | 说明 |
|---|---|---|
| LIGHTWEIGHT | `{lineStart, lineEnd}` | 原文行号，1-based |
| CSV | `{rowStart, rowEnd}` | 物理 CSV 行号，表头为第 1 行 |
| MINERU | `{pageNo, blockIndex}` | 页码（page_idx+1）+ content_list 序号 |
| DOCLING | `{pageNo, blockIndex, selfRef}` | 页码（prov.page_no）+ body 树遍历序号 + DoclingDocument 自引用（如 `#/texts/2`） |

引用溯源（`citation → chunk → source_locator`）按 `Document.parser_name` 解释 locator。

### 共享切块器

`markdown_blocks.split_markdown_blocks()`（自 LightweightParser 提取）：ATX 标题维护 `title_path` 面包屑且不出块、空行分段。LightweightParser 直接使用；MinerUParser 在 content_list 缺失时回退使用。

## 四、格式路由表

| 扩展名 | 解析器 | file_type | 可用条件 |
|---|---|---|---|
| .md / .markdown | LIGHTWEIGHT | MARKDOWN | 恒可用 |
| .txt | LIGHTWEIGHT | TEXT | 恒可用 |
| .csv | CSV | CSV | 恒可用 |
| .pdf | MINERU / DOCLING | PDF | 对应引擎已配置 |
| .docx | MINERU / DOCLING | WORD | 同上 |
| .pptx | MINERU / DOCLING | PPT | 同上 |
| .xlsx | MINERU / DOCLING | EXCEL | 同上 |
| .png / .jpg / .jpeg | MINERU / DOCLING | IMAGE | 同上 |
| .html / .htm | DOCLING（独占） | HTML | `DOCLING_BASE_URL` 已配置且引擎未锁定为 mineru |

链上顺序 `Lightweight → Csv → 重型引擎`，取第一个 `supports()` 命中者。自 Docling 接入后，两个重型引擎的扩展名**存在重叠，链序开始承载语义**：`auto` 模式下 MinerU 在前，共有格式全部归 MinerU，Docling 只接收其独占的 .html/.htm（详见 §十二）。旧版 office 格式（.doc/.ppt/.xls）不受理——两个引擎均仅支持 OOXML。

## 五、上传白名单策略

`registry.allowed_upload_extensions()`：

- `UPLOAD_ALLOWED_EXTENSIONS` **未设置**（默认）→ 白名单 = 所有**可用**解析器的扩展名并集；
- **已设置** → 白名单 = env ∩ 解析器支持集（**只能收紧，不能放宽**）。

`settings_service` 的 `filePolicy.allowedExtensions` 默认值同样取自该函数，管理界面展示的即生效白名单。

> ⚠️ 迁移注意：升级后存量 `.env` 中残留的 `UPLOAD_ALLOWED_EXTENSIONS=.md,.markdown,.txt` 会按交集语义把白名单钉死在旧集合——启用新格式前必须删掉或扩充该行（`.env.example` 已改为注释掉）。

## 六、CsvParser 设计

- 解码 `utf-8-sig`（剥 Excel 的 BOM），失败 → `PARSER_DECODE_ERROR`（不可重试）；
- `csv.Sniffer` 在 `,;\t|` 中嗅探分隔符，失败回退标准逗号方言；
- 单元格归一化：内嵌换行折叠为空格、`|` 转义为 `\|`；
- 输出 markdown 表格；按 `_MAX_BLOCK_CHARS = 4000` 分块（< `QA_SPLIT_MAX_BATCH_CHARS = 6000`，保证一个块必然放得进一个 QA 拆分批次），**每块重复表头**使其对 QA 生成自包含，每块至少 1 数据行；
- `title_path = [文件名去后缀]`，`page_no = 1`。

已知限制：不支持 GBK/GB18030（中文 Windows Excel 常见导出编码），列入未来扩展。

## 七、MinerU 集成

### 部署形态

worker 通过 HTTP 调用自部署的 `mineru-api`（单实例）或 `mineru-router`（多实例/多 GPU，接口相同）。无 GPU 时 mineru-api 可跑 CPU pipeline 后端（吞吐低）。应用侧零新增 Python 依赖（复用 httpx）。

### 客户端（`MinerUClient`）

- `POST {base}/file_parse`（multipart，`return_md=true`、`return_content_list=true`，可选 `backend`/`lang` 透传）；
- 响应含 `task_id` → 每 `MINERU_POLL_INTERVAL_SECONDS` 轮询 `GET /tasks/{id}` 至终态，成功后取 `GET /tasks/{id}/result`；否则按直接结果解析。**提交调用的超时 = 整体截止时间**（直接模式是同步解析，响应在解析完成后才返回）；
- 传输错误与 408/429/5xx 按 `min(8, 0.5·2ⁿ)` 退避重试（`max_retries=2`）；
- **`_extract_result()` 是 mineru-api 版本间响应包络漂移的唯一改动点**（兼容平铺字段 / `{"data": …}` / 按文件名的 `{"results": …}` 三种形态，`content_list` 可为 JSON 字符串）。

### 失败语义矩阵

| 情形 | 错误码 | retryable | 依据 |
|---|---|---|---|
| 连接失败 / 超时 / 5xx·408·429（重试耗尽） | `PARSER_UNAVAILABLE` | ✅ | 基础设施问题，Celery 重试有意义 |
| 轮询超过 `MINERU_MAX_WAIT_SECONDS` | `PARSER_TIMEOUT` | ✅ | 可能是服务过载 |
| 其他 4xx | `PARSER_REQUEST_ERROR` | ❌ | 请求本身不被接受 |
| 服务端报任务失败（state=failed） | `PARSER_FAILED` | ❌ | 大概率坏文件；重试烧 3×整体截止时间（可调的判断项） |
| 响应缺 markdown 与 content_list | `PARSER_RESPONSE_INVALID` | ❌ | 版本包络漂移，需人工介入 |

### content_list → blocks 映射

- `text` 且 `text_level ≥ 1` → 更新 `title_path`（不出块，与 markdown 切块器行为一致）；
- `text` → 正文块；`equation` → LaTeX 文本块；
- `table` → `table_caption` 行 + `table_body`（HTML 原样保留，QA 模型可读；转 markdown 列入未来扩展）；
- `image` → 有 caption 则出 `[图片] {caption}` 块，无 caption 跳过并累计 1 条 warning；
- `page_no = page_idx + 1`，`page_count = max(page_no)`。

**回退**：content_list 缺失但有 markdown → 共享切块器切分（行号 locator、page_no=1，接受降级）+ warning；markdown 缺失但有 content_list → 由块合成 markdown + warning。

## 八、配置矩阵

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `UPLOAD_ALLOWED_EXTENSIONS` | （未设置） | 见 §5，只能收紧 |
| `DOC_PARSER_ENGINE` | `auto` | 重型引擎选择：auto / mineru / docling（见 §十二） |
| `MINERU_BASE_URL` | 空（禁用） | mineru-api / mineru-router 地址 |
| `MINERU_API_KEY` | 空 | 可选 Bearer（auth 代理场景） |
| `MINERU_TIMEOUT_MS` | 30000 | 单次 HTTP 调用超时（轮询类调用） |
| `MINERU_MAX_WAIT_SECONDS` | 600 | 单文档解析整体截止时间 |
| `MINERU_POLL_INTERVAL_SECONDS` | 3.0 | 任务轮询间隔 |
| `MINERU_BACKEND` / `MINERU_LANG` | 空 | 透传给 mineru-api 的可选表单字段 |
| `DOCLING_BASE_URL` | 空（禁用） | docling-serve 地址（默认端口 5001） |
| `DOCLING_API_KEY` | 空 | 以 `X-Api-Key` 头发送（服务端设 `DOCLING_SERVE_API_KEY` 时必填） |
| `DOCLING_TIMEOUT_MS` | 30000 | 单次 HTTP 调用超时 |
| `DOCLING_MAX_WAIT_SECONDS` | 600 | 单文档解析整体截止时间 |
| `DOCLING_POLL_INTERVAL_SECONDS` | 3.0 | 长轮询 `wait` 参数与客户端节奏 |
| `DOCLING_DO_OCR` / `DOCLING_OCR_LANG` / `DOCLING_PDF_BACKEND` | 空 | 透传给 docling-serve 的可选表单字段 |

## 九、健康检查与可观测性

- `GET /health` 新增 `mineru` 与 `docling` 检查：未配置 → `"unconfigured"`（不参与整体状态计算）；已配置 → `GET {base}/health`（1s 超时，docling 带 `X-Api-Key`）→ `up`/`down`。**引擎 down 只产生 `degraded`，永不 503**——解析降级为可重试的任务失败，不应影响 API 就绪性（与 redis 规则一致）。探针按配置驱动而非按 engine 选择驱动：停用某引擎时应同时清掉其 `*_BASE_URL`，否则其探针仍参与 degraded 判定；
- 解析失败细节照旧落 `TaskRun.error`（code/message/retryable/failedAt），经 `/logs/task-runs` 可查；
- 顺带修复：`DocumentChunk.token_count` 由 `len(content.split())`（中文整段算 1）改为 CJK 感知统计（每汉字 1 token、每字母数字连串 1 token）。QA 拆分与嵌入阶段的同类统计本期未动，列入已知问题。

## 十、迁移与上线顺序

1. 部署 mineru-api（有 GPU 用 `vlm`/`hybrid` 后端，无 GPU 用 CPU pipeline；多实例前置 mineru-router——任务状态在 mineru-api 进程内存中，多实例必须经 router 做粘性路由）；
2. **冒烟核对包络**：对部署好的 mineru-api 手工跑一个 PDF 导入任务，确认 `_extract_result` 匹配该版本响应（这是上线 checklist 的必做项，本仓库测试用的是 MockTransport）；
3. 应用侧配置 `MINERU_BASE_URL`（API 与 worker 都要），删除/扩充存量 `.env` 的 `UPLOAD_ALLOWED_EXTENSIONS`（见 §5 警告）；
4. 建议同时把 `UPLOAD_MAX_FILE_SIZE_BYTES` 调至 ~50MB（默认 10MB 对 PDF 偏小；前端 `DocumentUploadPanel` 的 10MB 文案与常量需同步）；
5. worker 容量评估：一个解析任务最多占用 parse 队列槽位 `MINERU_MAX_WAIT_SECONDS`（默认 600s），Celery 层再重试 3 次——parse 队列并发数按此设置；
6. 前端无需灰度开关：服务端是权威，未配置 MinerU 时上传新格式返回 415，面板已有错误提示路径。

## 十一、已知问题与未来扩展

- **MinerU 云 API 客户端**：`MinerUClient` 的 submit/poll/extract 结构与云 API 形状同构，可加 `MineruCloudClient` 实现同一 `parse_file` 接口；
- **CSV 的 GBK/GB18030 回退解码**；**HTML 表格转 markdown**；
- **office 本地轻量解析**（python-docx 等）作为 MinerU 不可用时的降级选项——新增 Adapter 即可，架构已就绪；
- `qa_split_service`/`embedding_service` 中的 `.split()` 计数与 `token_count` 语义统一；
- 上传面板从 `filePolicy.allowedExtensions` 动态拉取白名单（当前为前端硬编码 + 服务端权威校验）；
- `SettingsService` 的 filePolicy 仅展示、不参与校验（既有行为，未改动）。

## 十二、Docling 集成与引擎选择（2026-07-07 追加）

### 部署形态与客户端契约

第二重型引擎 [Docling](https://github.com/docling-project/docling) 通过 HTTP 调自部署的 [docling-serve](https://github.com/docling-project/docling-serve)（stable v1 API），与 MinerU 接入形态一致，共享 `parsers/_http.py` 的 `RetryingHttpClient` 底座（重试/退避/错误归一化——**retryable 语义是与 Celery 重试管道的契约，单点维护**）。

`DoclingClient` **一律走异步端点**（同步端点有约 2 分钟服务端超时，大文档必超）：

```
POST /v1/convert/file/async     multipart：files + to_formats=md&to_formats=json
                                + image_export_mode=placeholder（防图片 base64 内联撑爆 ParseArtifact）
                                + 可选 do_ocr / ocr_lang / pdf_backend 透传
GET  /v1/status/poll/{task_id}?wait=N    长轮询；客户端单次超时 = timeout + poll_interval
                                          （服务端会挂住连接 wait 秒，普通超时会误报）
GET  /v1/result/{task_id}       → {"document": {"md_content", "json_content"}, "status", "errors"}
```

`_extract_task_id` / `_extract_result` 是 docling-serve 版本包络漂移的唯一改动点（对应 MinerU 的同名方法）。认证用 `X-Api-Key` 头（服务端 `DOCLING_SERVE_API_KEY`）。失败语义矩阵与 MinerU **完全一致**（§七的五个错误码），Celery 层对两个引擎的重试行为无差别。

### DoclingDocument → blocks 映射

优先用 `json_content`（DoclingDocument）建块，按 `body.children` 的 `$ref` 树序遍历（visited 集合防不可信 JSON 成环；groups 递归；不递归 table/picture 的子引用防 caption 双发）：

- `title` → 面包屑根；`section_header.level` → 面包屑深度（均不出块，与 markdown 切块器一致）；
- `text` / `list_item` / `code` / `formula` → 文本块；**未知 label 有文本也出块**（label 词表漂移防护）；
- 防御性跳过 `page_header` / `page_footer` / `footnote` / 独立 `caption`（caption 经所属对象的 captions 引用附着）；
- `table` → 由 `data.grid` 合成 markdown 表格（竖线转义、空白折叠），caption 前置；
- `picture` → 解析 captions 引用 → `[图片] {caption}`；无 caption 跳过并聚合 warning（同 MinerU D4）；
- `page_no = prov[0].page_no`（已 1-based，HTML 等无分页格式为 null）；locator `{pageNo, blockIndex, selfRef}`。

回退与 MinerU 镜像：json_content 缺 → markdown 切分 + warning；md_content 缺 → `markdown_from_blocks` 合成 + warning；均缺 → `PARSER_RESPONSE_INVALID`。

### 引擎选择语义（`DOC_PARSER_ENGINE`）

| 取值 | 注册的重型解析器 | 行为 |
|---|---|---|
| `auto`（默认） | MinerU, Docling（此序） | 谁配置了 `*_BASE_URL` 用谁；**都配置时链序决定：共有格式（pdf/docx/pptx/xlsx/图片）全归 MinerU，Docling 只接收独占的 .html/.htm** |
| `mineru` | 仅 MinerU | Docling 即使配置了也不注册，.html/.htm 不进白名单 |
| `docling` | 仅 Docling | 全部重型格式（含共有七种 + html）归 Docling |
| 其他值 | 同 auto | warn-once 日志后按 auto 处理（注册表在上传门逐请求执行，typo 不应变成全量 500） |

**要点**：想让 Docling 解析 PDF，必须显式 `DOC_PARSER_ENGINE=docling`——auto 下 MinerU 优先是有意为之（中文文档解析质量优先、保持既有部署行为不变）。未配置引擎的格式照旧被上传门 415 拒绝，机制未变。停用某引擎时应同时清空其 `*_BASE_URL`（健康探针按配置驱动，见 §九）。

部署指南：[docs/deployment/docling-local.md](../../deployment/docling-local.md)。
