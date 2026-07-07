
可插拔文档解析架构 + MinerU 解析器实施计划

 Context（背景）

 server/app/integrations/parsers/mineru.py 是空壳（恒抛 PARSER_UNAVAILABLE），系统目前只能摄取 md/txt。目标：
 1. 把 parsers 目录重构为注册表驱动的可插拔解析器架构（保留 ParserAdapter 契约与 ParserError 重试语义，Celery 重试管道不动），未来可平滑加入 word/ppt/excel 等解析模块；
 2. 实现真正的 MinerUParser——HTTP 客户端调自部署 mineru-api（MinerU 3.x 原生支持 PDF/DOCX/PPTX/XLSX/PNG/JPG）；
 3. 新增本地 CsvParser（仅标准库）；
 4. 打通上传入口（扩展名白名单注册表化、_file_type 映射、前端 accept 列表）；
 5. 落一份中文架构设计文档到 docs/design/v1.1/07-document-parser-architecture.md。

 用户已定决策：MinerU 走自部署 HTTP 服务；csv 本地解析、pdf/docx/pptx/xlsx/图片走 MinerU、md/txt 走现有 LightweightParser；交付 = 设计文档 + 全量实施。

 关键设计决策

 - D1 上传白名单注册表化：upload_allowed_extensions 默认改为 ()（未设置哨兵）；registry 提供 allowed_upload_extensions() = env 未设→全部可用解析器扩展名并集；env 设置→env ∩
 registry（只能收紧不能放宽）。MinerU 未配置 MINERU_BASE_URL 时 is_available() 为 False → PDF/Office 扩展名不放行，杜绝"上传成功解析必败"。
 - D2 解析器元数据上收基类：类级 extensions/mime_types frozenset + is_available() 钩子（默认 True）；supports() 在基类给默认实现（后缀优先、mime 次之——客户端传的 content_type
 不可信）。
 - D3 MinerU HTTP 契约单点隔离：MinerUClient 独占端点路径/multipart 字段/响应包络探测（直接结果 vs task_id 轮询）/错误映射；_extract_result() 是版本漂移的唯一改动点。错误抛
 ParserError（不是 ProviderError）。
 - D4 图片块：content_list 中 image 有 caption → 块 "[图片] " + caption；无 caption 跳过并累计 1 条 warning。
 - D5 MinerU 任务级失败（服务端报 task failed）→ retryable=False（大概率坏文件，重试浪费 3×10min）；连接/超时/5xx → retryable=True。
 - D6 token_count 快修：document_parse_service.py:176 的 len(content.split()) 改为 CJK 感知：len(re.findall(r"[一-鿿]|[^\W_]+", content))。qa_split/embedding 处的 .split()
 不动（已知问题记录在文档）。
 - D7 /health 加 mineru 检查：未配置 → "unconfigured"（不参与状态计算）；配置了 → GET {base}/health 1s 超时，down 只导致 degraded 不导致 503（对齐 redis 规则）。
 - D8 CSV 分块：模块常量 _MAX_BLOCK_CHARS = 4000（< QA_SPLIT_MAX_BATCH_CHARS=6000），每块重复表头自包含，至少 1 数据行。

 文件改动

 新增

 ┌─────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
 │                        文件                         │                                                            内容                                                             │
 ├─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ server/app/integrations/parsers/markdown_blocks.py  │ split_markdown_blocks(markdown) -> list[ParsedBlock]——从 LightweightParser._split_blocks                                    │
 │                                                     │ 原样提取（标题+空行切分、title_path、{lineStart,lineEnd}）                                                                  │
 ├─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ server/app/integrations/parsers/registry.py         │ get_parser_chain()（顺序 Lightweight→Csv→MinerU）、supported_extensions()、allowed_upload_extensions()；仿                  │
 │                                                     │ storage/registry.py，调用时读 settings                                                                                      │
 ├─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │ server/app/integrations/parsers/csv_parser.py       │ CsvParser：utf-8-sig 解码（错→PARSER_DECODE_ERROR 不可重试）、csv.Sniffer 嗅探分隔符（,;\t|，失败回退 excel                 │
 │                                                     │ 方言）、竖线转义、换行折叠；markdown 表格分块、source_locator={"rowStart","rowEnd"}（1-based）、title_path=[文件名 stem]    │
 ├─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
 │                                                     │ 中文设计文档（编号文档头部惯例）：目标与非目标 / 总体架构图 / 契约与三种 locator 形态 / 格式路由表 / 上传白名单策略 /       │
 │ docs/design/v1.1/07-document-parser-architecture.md │ CsvParser / MinerU 集成与失败语义矩阵 / 配置矩阵 / 健康检查 / 迁移与灰度（先部署 mineru-api→配 env→放开前端；10MB           │
 │                                                     │ 上限建议调 50MB）/ 已知问题与未来扩展（云 API、GBK CSV、HTML 表转 md）                                                      │
 └─────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

 修改

 文件: parsers/base.py
 改动: ParserAdapter 加 extensions/mime_types/is_available() + 默认 supports()；数据类不动
 ────────────────────────────────────────
 文件: parsers/lightweight.py
 改动: 声明元数据、删手写 supports、复用 split_markdown_blocks
 ────────────────────────────────────────
 文件: parsers/mineru.py
 改动: 重写：MinerUClient（from_settings/configured/parse_file：POST /file_parse multipart + return_md/return_content_list，有 task_id 则轮询 /tasks/{id} 至终态或 monotonic 截止；重试
   {408,429,5xx}+传输错误，backoff min(8, 0.5·2ⁿ)）+ MinerUParser（content_list 优先建块：text_level 建 title_path 不出块、table 保 HTML、equation 保 LaTeX、page_idx+1→page_no、locator

   {pageNo,blockIndex}；content_list 缺失→markdown
   回退切分+warning；都缺→PARSER_RESPONSE_INVALID）。错误码：PARSER_UNAVAILABLE(可重试)/PARSER_TIMEOUT(可重试)/PARSER_REQUEST_ERROR/PARSER_FAILED/PARSER_RESPONSE_INVALID
 ────────────────────────────────────────
 文件: core/config.py
 改动: 新增 mineru_base_url/mineru_api_key/mineru_timeout_ms=30000/mineru_max_wait_seconds=600/mineru_poll_interval_seconds=3.0/mineru_backend/mineru_lang；upload_allowed_extensions
   默认 ()
 ────────────────────────────────────────
 文件: services/document_parse_service.py
 改动: 默认解析器链改 get_parser_chain()；token_count 快修（D6）
 ────────────────────────────────────────
 文件: services/import_service.py
 改动: _validate_file_limits 改用 allowed_upload_extensions()；_file_type 扩展映射（PDF/WORD/PPT/EXCEL/CSV/IMAGE）
 ────────────────────────────────────────
 文件: services/settings_service.py
 改动: filePolicy.allowedExtensions 默认值改为 sorted(allowed_upload_extensions())
 ────────────────────────────────────────
 文件: main.py
 改动: /health 加 _check_mineru()（D7）
 ────────────────────────────────────────
 文件: web/admin/src/features/knowledge/components/DocumentUploadPanel.tsx
 改动: ALLOWED_SUFFIXES(:16)、accept(:106)、三处文案(:32/:90/:167) 扩为全格式；服务端仍是权威（未配置 MinerU 时 415 已有提示路径）
 ────────────────────────────────────────
 文件: .env.example
 改动: 注释掉 UPLOAD_ALLOWED_EXTENSIONS，新增 MINERU_* 配置块

 测试

 - 新增 test_csv_parser.py：逗号/分号嗅探、BOM、竖线转义、4000 字符分块（表头自包含）、非 UTF-8 → PARSER_DECODE_ERROR、空文件 0 块
 - 新增 test_mineru_parser.py（仿 test_model_providers_http.py:14 的 MockTransport + no-op sleep/monotonic 模式）：直接结果模式、task 轮询模式、503 重试后成功、持续
 503/ConnectError→PARSER_UNAVAILABLE(retryable)、4xx→PARSER_REQUEST_ERROR(不可重试)、轮询超时→PARSER_TIMEOUT、content_list 映射（page_no/title_path/表格/无 caption
    图片跳过+warning/公式/locator）、markdown 回退+warning、未配置时 supports()=False
 - 新增 test_parser_registry.py：扩展名路由、未配置 MinerU 时 supported_extensions 排除其格式、allowed_upload_extensions 的 env 交集语义
 - 改 test_parse_document_task.py：失败用例改为"显式注入配置了但不可达的 MinerU"→ PARSER_UNAVAILABLE retryable=True；新增默认链下 .pdf → UNSUPPORTED_FILE_TYPE；新增 .csv 端到端任务
 - 改 test_import_jobs.py：.csv 默认放行；.pdf 未配置 MinerU 时 415、配置后放行；file_type 映射
 - 改 test_config.py：MINERU_* 字段、upload_allowed_extensions 新默认

 验证

 1. python -m pytest server/tests -q 全绿
 2. python -m server.scripts.export_openapi（若 settings schema 有变化则重新生成）
 3. web/admin: npm run typecheck && npm run build
 4. 冒烟核对（文档中列入上线 checklist，本地无 mineru-api 则跳过）：对真实 mineru-api 跑一个 PDF 导入任务，确认 _extract_result 包络匹配

 风险备忘（写入设计文档）

 - mineru-api 各 3.x 版本响应包络有漂移——_extract_result 单点隔离 + 上线前冒烟；
 - 默认 10MB 上限对 PDF 偏小（前端也硬编码 10MB）——上线建议调 50MB，本次不改默认值；
 - 解析任务最多阻塞 worker 槽位 600s×3 次重试——parse 队列并发按此评估；
 - 存量 .env 中残留的 UPLOAD_ALLOWED_EXTENSIONS=.md,... 会按交集语义钉死旧白名单——迁移说明必须提。