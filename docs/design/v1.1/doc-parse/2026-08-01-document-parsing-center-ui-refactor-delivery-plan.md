# 文档解析中心页面重构 Delivery Plan

## Objective and Completion Definition

**Objective**：将 `#knowledge` 文档解析中心重构为“任务构建器 + 任务处理流水线 + 文档处理列表”的工作台，并提供当前用户可见的文档/Chunk 汇总统计。

**Completion Definition**：

- `#knowledge` 在桌面端呈现参考图同类的信息层级：标题与指标、左侧任务构建器、右侧四步流水线、下方紧凑文档列表；
- 知识库分类位于提交按钮上方，“所有登录用户可访问”位于分类下方，部门/角色/用户 ID 位于该开关之后且位于提交按钮之前；
- 流水线只展示真实后端阶段，移除不存在的 `INDEXING`；
- 顶部指标由 `DOCUMENT_READ` 权限保护的 summary API 提供，不依赖 dashboard 权限；
- 上传、分类、权限、解析轮询、失败信息、详情跳转和现有文档管理页均不回归；
- 后端目标测试、前端类型检查/构建和 T09 浏览器验收通过。

## Preconditions

1. 在开始修改前记录并保留现有工作区改动；不得覆盖下列已经修改的验收截图：
   - `docs/development/v1.1/acceptance/t09-knowledge-upload-desktop.png`
   - `docs/development/v1.1/acceptance/t09-knowledge-desktop.png`
   - `docs/development/v1.1/acceptance/t09-knowledge-mobile.png`
2. 后端测试环境可使用 `python -m pytest`，并能初始化现有 SQLite/测试数据库。
3. 前端依赖已安装在 `web/admin/node_modules`，可运行 `npm run typecheck`、`npm run build`。
4. 确认流水线文案采用真实阶段映射：文档解析、知识切分与 QA 问答生成、向量化与知识入库、完成上架可检索；本次不调整 Worker 执行顺序。
5. 确认当前 OpenAPI 生成流程可更新：`web/admin/openapi.json` 与 `web/admin/src/api/schema.d.ts` 必须同后端接口一致。

## Execution Sequence

1. T-001 保护现有改动并建立基线。
2. T-002 为 summary 接口写失败测试。
3. T-003 实现 repository/service/schema/API 的 summary 合约。
4. T-004 更新 OpenAPI 和前端 API 类型封装。
5. T-005 重构解析中心页面的数据装配与顶栏指标。
6. T-006 重排上传任务构建器的字段与交互。
7. T-007 将旧时间轴改造成真实阶段流水线。
8. T-008 增加解析中心专用文档处理列表。
9. T-009 新增页面专属桌面/移动端样式和无障碍细节。
10. T-010 更新 Playwright mock、端到端断言和验收截图策略。
11. T-011 执行全量验证、完成回归检查并记录交付结果。

## Detailed Tasks

### T-001 — 保护现有改动并建立改造基线

- **Purpose**：防止重构和自动截图覆盖用户已有工作；记录改造前的构建、测试和目标页面行为。
- **Files**：`docs/development/v1.1/acceptance/t09-knowledge-upload-desktop.png`、`docs/development/v1.1/acceptance/t09-knowledge-desktop.png`、`docs/development/v1.1/acceptance/t09-knowledge-mobile.png`（只读核对，原因是这些文件当前已有工作区改动）；`docs/design/v1.1/doc-parse/2026-08-01-document-parsing-center-ui-refactor-analysis.md`（新增，原因是固定当前分析结论）；`docs/design/v1.1/doc-parse/2026-08-01-document-parsing-center-ui-refactor-delivery-plan.md`（新增，原因是固定实施顺序）。
- **Implementation**：执行 `git status --short` 并保存当前改动范围；在运行任何会写入 acceptance 截图的 Playwright 命令前，将相关 PNG 复制到工作区外的临时备份目录。不得使用 `git reset`、`git checkout --` 或删除用户现有改动。确认当前 `#knowledge` 渲染的是 `ImportPage -> KnowledgePage`，并确认 “文档管理”页 `#document-management` 不在本次替换范围内。
- **Dependencies**：无。
- **Verification**：运行 `git status --short`；运行 `npm run typecheck`（工作目录 `web/admin`）。期望：状态输出仍包含原有改动，类型检查在改造前通过或记录既有失败。
- **Done when**：现有修改已记录并保留；设计分析和交付计划文件存在；后续测试不会无意覆盖现有验收截图。

### T-002 — 为文档解析中心汇总接口编写失败测试

- **Purpose**：落实“已同步文档”和“已解析 Chunks”必须按租户、软删除状态和访问范围聚合的设计决策。
- **Files**：`server/tests/test_knowledge_documents_api.py`（修改，新增 summary API 测试）；`server/app/api/v1/documents.py`（后续实现目标）；`server/app/services/document_center_service.py`（后续实现目标）；`server/app/repositories/document_repo.py`（后续实现目标）。
- **Implementation**：在现有文档 API 测试中增加 `test_document_summary_returns_visible_document_and_chunk_totals`。测试数据至少包含：同一租户两个可见文档（`chunk_count` 分别为 3 和 5）、一个 `DELETED` 文档（`chunk_count` 为 99）、一个其他租户文档（`chunk_count` 为 88）。以具有 `DOCUMENT_READ` 权限的用户请求 `GET /api/v1/documents/summary`，断言 HTTP 200、`syncedDocumentCount == 2`、`totalChunkCount == 8`。再增加非管理员访问范围用例，断言无匹配访问规则的文档不进入汇总。
- **Dependencies**：T-001；复用 `build_test_client`、已有登录辅助函数和现有文档模型/权限规则测试夹具。
- **Verification**：运行 `python -m pytest server/tests/test_knowledge_documents_api.py -k summary -v`。期望：在接口实现前出现 404 或断言失败。
- **Done when**：测试明确约束 API 路径、camelCase 字段、删除过滤、租户隔离和访问范围；测试失败原因仅为 summary 尚未实现。

### T-003 — 实现可见文档与 Chunk 的 summary API

- **Purpose**：为解析中心顶部统计提供最小、权限正确且不依赖 Dashboard 的后端数据源。
- **Files**：`server/app/schemas/document.py`（修改，新增 `DocumentProcessingSummaryResponse`）；`server/app/repositories/document_repo.py`（修改，新增 `summarize_documents(context)`）；`server/app/services/document_center_service.py`（修改，新增 `summary(context)`）；`server/app/api/v1/documents.py`（修改，新增 `GET /summary`，并放在 `/{document_id}` 之前）。
- **Implementation**：
  1. 在 `DocumentProcessingSummaryResponse` 中定义 `synced_document_count: int = Field(alias="syncedDocumentCount")` 和 `total_chunk_count: int = Field(alias="totalChunkCount")`，并启用 `populate_by_name=True`。
  2. 在 `DocumentRepository` 内新增公开聚合方法，复用现有 `_document_filters` 或等价的访问控制条件；不得绕过非管理员的 `_access_exists(context)` 逻辑。
  3. 聚合查询限定 `Document.tenant_id == context.tenant_id`、`Document.deleted_at.is_(None)` 和 `Document.status != DocumentStatus.DELETED`；使用 `COUNT(Document.id)` 与 `COALESCE(SUM(Document.chunk_count), 0)`，确保空库返回两个零值而不是 `null`。
  4. 在 `DocumentCenterService.summary` 中仅返回 `{"synced_document_count": ..., "total_chunk_count": ...}`；不得复用 dashboard service，不得修改 `ImportService`、Worker 或数据库模型。
  5. 在 documents router 增加 `@router.get("/summary", response_model=DocumentProcessingSummaryResponse)`，使用 `require_permission("DOCUMENT_READ")`。
- **Dependencies**：T-002。
- **Verification**：运行 `python -m pytest server/tests/test_knowledge_documents_api.py -k summary -v`。期望：所有新增 summary 测试通过。随后运行 `python -m pytest server/tests/test_knowledge_documents_api.py -v`。期望：整个文件通过。
- **Done when**：`GET /api/v1/documents/summary` 返回两个 camelCase 整数；测试验证删除、跨租户和无访问权限文档不会泄露到统计中。

### T-004 — 同步 OpenAPI 并封装前端文档统计客户端

- **Purpose**：让前端以类型安全方式调用 summary API，避免手写接口与 FastAPI schema 漂移。
- **Files**：`web/admin/openapi.json`（修改，加入 `/api/v1/documents/summary` 和 response schema）；`web/admin/src/api/schema.d.ts`（修改，重新生成类型）；`web/admin/src/features/knowledge/api/documentApi.ts`（修改，新增 `DocumentProcessingSummary` 类型和 `getDocumentProcessingSummary()`）。
- **Implementation**：先从已运行的 FastAPI OpenAPI 输出更新 `web/admin/openapi.json`，再在 `web/admin` 中运行 `npm run gen:api` 生成 `schema.d.ts`。在 `documentApi.ts` 中以生成的 schema 定义为来源声明返回类型，并实现 `getDocumentProcessingSummary()` 调用 `/api/v1/documents/summary`。不得通过调用 `/api/v1/dashboard/summary` 获取数据，因为该接口要求 `DASHBOARD_READ`，与解析中心的 `DOCUMENT_READ` 访问边界不一致。
- **Dependencies**：T-003；本地后端必须能暴露最新 OpenAPI 文档。
- **Verification**：运行 `npm run typecheck`（工作目录 `web/admin`）。可选手工验证：携带有 `DOCUMENT_READ` 但没有 `DASHBOARD_READ` 的令牌请求 summary，期望 HTTP 200。
- **Done when**：前端不存在匿名 `any` 的 summary 响应；OpenAPI JSON、生成类型和后端 schema 三者字段一致。

### T-005 — 重构解析中心页面装配与顶部指标

- **Purpose**：把 `#knowledge` 从简单双栏页面升级为具有页面标题、同步指标、主工作区和下方列表容器的工作台。
- **Files**：`web/admin/src/features/knowledge/pages/KnowledgePage.tsx`（修改，负责页面状态、轮询与数据刷新）；`web/admin/src/features/knowledge/api/documentApi.ts`（使用 T-004 新增方法）；`web/admin/src/features/knowledge/components/DocumentProcessingList.tsx`（后续新增组件）。
- **Implementation**：
  1. 在 `KnowledgePage` 中保留 `activeJob` 以及现有仅对 `PENDING`、`RUNNING` 任务进行 2 秒轮询的逻辑。
  2. 增加 summary 状态、文档列表状态、错误状态和加载状态；首次挂载时并行加载 `getDocumentProcessingSummary()` 与 `listDocuments({ keyword: "", fileType: "", status: "", spaceId: "", classificationDepartmentId: "", categoryId: "", isUnclassified: false, departmentId: "", roleId: "", page: 1, pageSize: 10 })`。
  3. 上传成功回调中先设置 `activeJob`，随后刷新 summary 和第一页文档列表；轮询到 `COMPLETED` 或 `FAILED` 后再刷新一次，确保 Chunk 数和同步状态最终一致。
  4. 页面头使用“文档解析与知识提炼中心”和简短说明；右侧展示两个只读指标及加载占位。标题、数字、单位使用语义化文本，而非背景图片。
  5. 保留到 `#documents`、`#knowledge-classification` 的现有导航能力，但将它们降级为列表区域或页面头的次级文本入口，不抢占主任务构建按钮的视觉层级。
- **Dependencies**：T-004；T-008 的组件接口。
- **Verification**：运行 `npm run typecheck`（工作目录 `web/admin`）；手工打开 `/#knowledge`，验证首次请求包含 `/api/v1/documents/summary` 与 `/api/v1/documents?page=1&pageSize=10`。
- **Done when**：页面在无任务、加载任务、完成任务三种状态均可渲染；上传成功会刷新统计和列表，不需要整页刷新。

### T-006 — 重排一键构建解析任务表单

- **Purpose**：按参考布局将分类、访问权限和 ID 范围移动到“一键构建解析任务”按钮上方，同时保持原有上传请求语义。
- **Files**：`web/admin/src/features/knowledge/components/DocumentUploadPanel.tsx`（修改）；`web/admin/src/features/knowledge/components/KnowledgeClassificationSelect.tsx`（只在需要提供紧凑展示 props 时修改，避免改变其他调用点）；`web/admin/src/styles.css`（后续由 T-009 修改）。
- **Implementation**：
  1. 保留 `file`、`allAuthenticated`、`departmentIds`、`roleIds`、`userIds`、`classificationValue`、上传进度和错误状态。
  2. 上传区域移动到卡片开头，使用现有 `<input type="file">`，保留拖放、格式白名单、10MB 前端限制、文件名自动生成标题和 SHA-256 checksum 逻辑。
  3. 将 `KnowledgeClassificationSelect` 置于提交按钮前；紧随其后放置“所有登录用户可访问”复选框；再放置部门、角色、用户 ID 三个输入框；最后放置全宽主按钮“▷ 一键构建解析任务”。
  4. 全员访问为 true 时禁用三个 ID 输入框；为 false 时继续执行“至少选择一种访问范围”的原有校验。分类仍使用 `validateClassificationValue(..., { allowUnclassified: true })`，不得将分类变成必填。
  5. 不展示参考图中尚未有对应后端 `parseOptions` 契约的可编辑 Chunk Size/Overlap 滑块；本期改为准确的“默认智能切分策略”说明，避免将未提交的数据伪装成生效配置。
  6. 人工标题输入框不再作为主表单字段；创建任务时继续使用 `title.trim() || file.name` 或文件名去扩展名，以满足后端 title 必填约束且不改变 API。
- **Dependencies**：T-005；现有 `createImportJob`、`uploadImportJobFile`、分类和权限接口。
- **Verification**：运行 `npm run typecheck`（工作目录 `web/admin`）；在浏览器选择 `.md` 文件、选择完整分类路径、取消“所有登录用户可访问”、填写部门 ID 后提交，检查 `POST /api/v1/import-jobs` 请求体仍带有 `title`、`classification`、`permission` 和 `processingOptions`。
- **Done when**：字段顺序满足设计；上传、拖放、错误提示、禁用逻辑和请求载荷与改造前保持兼容。

### T-007 — 将任务进度重构为真实阶段流水线

- **Purpose**：将旧的英文阶段列表改造成参考图的纵向流水线，并消除不存在的 `INDEXING` 阶段。
- **Files**：`web/admin/src/features/knowledge/components/ImportJobTimeline.tsx`（修改）；`web/admin/src/styles.css`（后续由 T-009 修改）。
- **Implementation**：
  1. 定义四个显示步骤及后端阶段映射：`PARSING` -> “文档解析”，`QA_SPLITTING` -> “知识切分与 QA 问答生成”，`EMBEDDING` -> “向量化与知识入库”，`COMPLETED` -> “完成上架，可检索使用”。
  2. 对 `job === null` 显示“空闲”标签和“上传文档并点击一键构建解析任务后开始处理”的说明；四个步骤均显示非激活外观。
  3. 对 `PENDING`/`CREATED` 显示排队状态，不将其伪造成已开始解析；对 `RUNNING` 根据 `stage` 标记已完成步骤和当前步骤；对 `COMPLETED` 标记全部完成；对 `FAILED` 标记失败阶段、显示 `errorCode` 与 `errorMessage`，并在 `retryable` 时提供重试入口或明确指向现有任务详情/重试能力。
  4. 保留 `progress` 作为辅助状态文本和可访问标签，不把百分比作为判断完成步骤的唯一依据。
  5. 不新增 `INDEXING`、`QA_VALIDATING` 或其他后端不存在的状态，不修改 `ImportService`、`DocumentParseService` 或 `EmbeddingService` 的阶段顺序。
- **Dependencies**：T-005；现有 `ImportJob` 的 `status`、`stage`、`progress`、`errorCode`、`errorMessage`、`retryable` 字段。
- **Verification**：在组件级或 Playwright mock 中分别喂入 `null`、`PARSING`、`QA_SPLITTING`、`EMBEDDING`、`COMPLETED`、`FAILED` 任务；确认没有 `INDEXING` 文本。运行 `npm run typecheck`（工作目录 `web/admin`）。
- **Done when**：每个真实后端阶段都有唯一、可解释的视觉状态；空闲、进行中、完成和失败均有明确文字与无障碍标签。

### T-008 — 新增解析中心紧凑文档处理列表

- **Purpose**：在解析中心内展示参考图同类的已同步/正在处理文档，避免用户必须跳转到完整文档管理页才能确认上传结果。
- **Files**：`web/admin/src/features/knowledge/components/DocumentProcessingList.tsx`（新增）；`web/admin/src/features/knowledge/pages/KnowledgePage.tsx`（修改，传入状态和回调）；`web/admin/src/features/knowledge/api/documentApi.ts`（使用已有 `listDocuments`）；`web/admin/src/styles.css`（后续由 T-009 修改）。
- **Implementation**：
  1. 创建受控组件，props 至少包含 `documents`、`pagination`、`keyword`、`loading`、`error`、`onKeywordChange`、`onRefresh`、`onPageChange`。
  2. 表头展示“文档名称与归属”“知识分类空间”“切分 Chunks 数”“同步状态”“管理调试”。每行显示 `title`、`updatedAt`、`fileSize`、`classification?.spaceName ?? "未分类知识库"`、`chunkCount` 和状态文案。
  3. 状态映射准确反映 `UPLOADED`、`PARSING`、`QA_SPLITTING`、`EMBEDDING`、`READY`、`FAILED`；`READY` 使用“已注入向量库”或“可检索”，处理中显示实际阶段，失败显示“解析失败”。
  4. “查看详情”跳转到 `#document-management-detail?documentId=<encoded id>`；“切片预览”只在已有详情页可以显示 Chunk 时使用同一详情入口或锚点，不新造无后端支持的预览 API。
  5. 搜索框使用 `<input type="search" aria-label="检索已同步文档">`，变更时把页码重置为 1；加载中显示骨架/状态文本，空数据展示“暂无符合条件的文档”。
- **Dependencies**：T-005；`KnowledgeDocument`、`Pagination`、`listDocuments` 与已有详情页路由。
- **Verification**：手工在 `#knowledge` 搜索一个已知标题，确认请求含 `keyword` 和 `page=1`；点击详情确认 URL 包含目标 `documentId`；运行 `npm run typecheck`（工作目录 `web/admin`）。
- **Done when**：列表可搜索、刷新、分页、查看详情，且不会替换或削弱 `#document-management` 的完整管理功能。

### T-009 — 实现专属样式、响应式布局和无障碍细节

- **Purpose**：使页面在视觉上接近参考图，同时避免共享 CSS 影响其他知识库、文档管理或聊天页面。
- **Files**：`web/admin/src/styles.css`（修改，新增 `document-processing-*` 命名空间）；`web/admin/src/features/knowledge/pages/KnowledgePage.tsx`（必要时增加语义 class）；`web/admin/src/features/knowledge/components/DocumentUploadPanel.tsx`、`ImportJobTimeline.tsx`、`DocumentProcessingList.tsx`（必要时增加语义 class）。
- **Implementation**：
  1. 新增页面专属类：`document-processing-page`、`document-processing-header`、`document-processing-metrics`、`document-processing-workspace`、`document-processing-uploader`、`document-processing-pipeline`、`document-processing-list`。
  2. 桌面端采用左窄右宽布局；列表独占下一行；统一白色卡片、浅灰边框、圆角、蓝色主操作、稳定的 8/12/16/24px 间距层级。
  3. 流水线使用图标容器、连接线、当前/已完成/失败/空闲状态；颜色外必须有文字、图标或 `aria-label` 区分。
  4. 拖拽区域必须保留可聚焦的文件选择输入；搜索输入、刷新按钮、详情按钮、提交按钮均使用原生可访问元素；纯图标按钮必须提供 `aria-label`。
  5. 在现有 `@media (max-width: 860px)` 中将工作区改为单列，指标可换行，表格采用横向滚动容器或移动端卡片信息排列；不得让分类三个选择框或 ID 输入框溢出视口。
  6. 不修改 `.knowledge-grid`、`.timeline` 的通用语义以“全局覆盖”实现页面差异；优先使用新增命名空间，防止影响旧页面和组件。
- **Dependencies**：T-005、T-006、T-007、T-008。
- **Verification**：在 1440px、1024px、768px 和 320px 宽度下打开 `#knowledge`；键盘使用 Tab 遍历上传、分类、访问控制、提交、搜索和详情入口；运行 `npm run build`（工作目录 `web/admin`）。
- **Done when**：页面无横向意外溢出，所有主交互可键盘访问，桌面与移动端均能完整查看流水线和文档列表。

### T-010 — 更新浏览器验收 mock 与端到端场景

- **Purpose**：使自动化验收覆盖新 summary 请求、重排后的表单、真实阶段流水线和上传后列表刷新。
- **Files**：`web/admin/tests/t09_knowledge_playwright.py`（修改）；`docs/development/v1.1/acceptance/t09-knowledge-upload-desktop.png`、`docs/development/v1.1/acceptance/t09-knowledge-desktop.png`、`docs/development/v1.1/acceptance/t09-knowledge-mobile.png`（仅在备份后且验收通过后更新）。
- **Implementation**：
  1. 在 `KnowledgeApiMock` 中模拟 `GET /api/v1/documents/summary`，返回固定 `syncedDocumentCount`、`totalChunkCount`；同时保证 `GET /api/v1/documents` 返回含 `chunkCount`、分类和状态的数据。
  2. 将旧断言“文档入库、权限和 QA 结果”替换为新页面标题；将“创建导入任务”替换为“一键构建解析任务”。
  3. 保留分类选择、文件选择、`POST /api/v1/import-jobs` 请求载荷和 multipart 上传断言；新增断言确认分类在按钮前、全员访问开关在分类后、三个 ID 输入框受开关控制。
  4. 对完成任务断言四步流水线全部完成，且页面不存在 `INDEXING`；对空闲/失败 mock 增加必要断言。
  5. 提交上传后断言页面重新请求 summary 和 documents 列表，并在列表中出现 mock 文档或更新状态。
  6. 先将现有截图备份至临时目录；只有测试通过后才覆盖 acceptance 图片。
- **Dependencies**：T-005 至 T-009；T-001 的截图保护措施。
- **Verification**：运行 `python web/admin/tests/t09_knowledge_playwright.py`。期望：脚本退出码为 0，所有 `expect` 通过，截图仅在备份完成后更新。
- **Done when**：浏览器验收覆盖新的主路径，且现有上传 API、分类和权限载荷断言继续存在。

### T-011 — 执行回归验证并完成交付检查

- **Purpose**：在交付前确认接口契约、前端构建、核心后端导入链路和浏览器体验均无回归。
- **Files**：`server/tests/test_knowledge_documents_api.py`、`server/tests/test_import_jobs.py`、`web/admin/tests/t09_knowledge_playwright.py`（只执行）；`docs/design/v1.1/doc-parse/2026-08-01-document-parsing-center-ui-refactor-delivery-plan.md`（修改 Progress Log 和 Decision Log）。
- **Implementation**：按验证矩阵的顺序运行测试；记录每条命令的结果、失败根因及修复动作。手工验证具备 `DOCUMENT_READ` 且不具备 `DASHBOARD_READ` 的账户仍能查看解析中心 summary；验证无 `DOCUMENT_UPLOAD` 权限时上传主操作按照现有 PermissionGate/后端校验拒绝。不得以跳过测试、删除断言或放宽权限来获得通过。
- **Dependencies**：T-002 至 T-010。
- **Verification**：
  - `python -m pytest server/tests/test_knowledge_documents_api.py -v`
  - `python -m pytest server/tests/test_import_jobs.py -v`
  - `npm run typecheck`（工作目录 `web/admin`）
  - `npm run build`（工作目录 `web/admin`）
  - `python web/admin/tests/t09_knowledge_playwright.py`
  - 手工检查 1440px、1024px、768px、320px。
- **Done when**：所有命令退出码为 0；手工验收通过；Progress Log 记录真实完成状态；不存在未解释的 API、类型、样式或截图差异。

## File Change Map

| 文件 | 操作 | 责任与原因 |
| --- | --- | --- |
| `server/app/schemas/document.py` | 修改 | 定义解析中心 summary 响应 schema。 |
| `server/app/repositories/document_repo.py` | 修改 | 在既有文档访问控制边界上聚合可见文档和 Chunk 总数。 |
| `server/app/services/document_center_service.py` | 修改 | 暴露 summary 服务方法，不耦合 Dashboard。 |
| `server/app/api/v1/documents.py` | 修改 | 新增 `GET /documents/summary`，权限为 `DOCUMENT_READ`。 |
| `server/tests/test_knowledge_documents_api.py` | 修改 | 覆盖 summary 统计、软删除、租户与权限隔离。 |
| `web/admin/openapi.json` | 修改 | 同步 FastAPI 新接口定义。 |
| `web/admin/src/api/schema.d.ts` | 修改 | 由 OpenAPI 重新生成的 TypeScript 类型。 |
| `web/admin/src/features/knowledge/api/documentApi.ts` | 修改 | 新增 summary 客户端和类型。 |
| `web/admin/src/features/knowledge/pages/KnowledgePage.tsx` | 修改 | 装配标题指标、上传刷新、流水线和文档处理列表。 |
| `web/admin/src/features/knowledge/components/DocumentUploadPanel.tsx` | 修改 | 重排构建任务字段与主操作视觉层级。 |
| `web/admin/src/features/knowledge/components/ImportJobTimeline.tsx` | 修改 | 替换为真实阶段四步流水线。 |
| `web/admin/src/features/knowledge/components/DocumentProcessingList.tsx` | 新增 | 提供解析中心专用的紧凑搜索/处理列表。 |
| `web/admin/src/styles.css` | 修改 | 增加页面专属桌面、移动端和状态样式。 |
| `web/admin/tests/t09_knowledge_playwright.py` | 修改 | 更新 mock、断言和截图验收。 |
| `docs/development/v1.1/acceptance/t09-knowledge-*.png` | 条件修改 | 仅在备份、测试通过和视觉验收后更新。 |

## Data Migration / Feature Flag Plan

- **Data migration**：不需要。summary 使用现有 `documents.chunk_count`、租户字段、软删除字段和访问规则表；不增加列、不回填数据、不修改 Alembic migration。
- **Feature flag**：不需要。解析中心为内部后台功能，页面与接口可同一版本发布。
- **Compatibility**：保留现有 `POST /api/v1/import-jobs`、文件上传、任务查询和文档列表接口。新 summary API 为加法改动；旧“文档管理”页不依赖本次新增的前端组件。
- **Rollback**：如出现 summary 性能或权限问题，可仅回滚页面对 `/documents/summary` 的调用并将顶部指标显示为不可用；导入任务、文档数据和 Worker 状态不会受影响。

## Validation Matrix

| 验证项 | 位置 | 命令/步骤 | 通过标准 |
| --- | --- | --- | --- |
| Summary API 精确统计 | 后端 | `python -m pytest server/tests/test_knowledge_documents_api.py -k summary -v` | 文档数和 Chunk 数正确；删除、跨租户、无访问权数据不计入。 |
| 文档 API 回归 | 后端 | `python -m pytest server/tests/test_knowledge_documents_api.py -v` | 整个测试文件通过。 |
| 导入任务回归 | 后端 | `python -m pytest server/tests/test_import_jobs.py -v` | 创建、分类、权限、multipart 上传和重试场景通过。 |
| TypeScript 类型 | 前端 | `npm run typecheck`，工作目录 `web/admin` | 退出码 0。 |
| 生产构建 | 前端 | `npm run build`，工作目录 `web/admin` | TypeScript 与 Vite build 均成功。 |
| 浏览器主路径 | 前端 | `python web/admin/tests/t09_knowledge_playwright.py` | 新标题、分类/权限顺序、构建任务、summary、流水线、列表和截图断言通过。 |
| 权限边界 | 手工/API | 使用仅有 `DOCUMENT_READ` 的账号访问 `/api/v1/documents/summary` | HTTP 200，且无需 `DASHBOARD_READ`。 |
| 文件上传权限 | 手工/API | 使用无 `DOCUMENT_UPLOAD` 的账号提交任务 | 拒绝上传，页面显示已有错误处理。 |
| 响应式布局 | 手工 | 在 1440、1024、768、320px 打开 `#knowledge` | 无意外横向溢出，表单、流水线、列表均可用。 |
| 键盘与状态语义 | 手工 | Tab 遍历所有交互；模拟空闲、处理中、失败状态 | 可聚焦；失败、完成、处理中不只依赖颜色区分。 |

## Risks and Contingencies

| 风险 | 影响 | 应对措施 |
| --- | --- | --- |
| 将 dashboard summary 用于解析中心 | 只拥有 `DOCUMENT_READ` 的用户无法看统计，或权限边界不清晰 | 使用独立 `/api/v1/documents/summary`，由 `DOCUMENT_READ` 保护。 |
| summary 聚合绕过文档可见范围 | 可能泄露其他部门/角色/用户的文档数量 | 在 `DocumentRepository` 复用与 `list_documents` 相同的访问过滤；为非管理员添加测试。 |
| 在前端继续保留 `INDEXING` | UI 状态与 Worker 不一致，用户无法理解任务位置 | 只映射 `CREATED`、`PARSING`、`QA_SPLITTING`、`EMBEDDING`、`COMPLETED`。 |
| 为匹配参考图而改变 QA/Embedding 顺序 | 影响队列、重试、文档状态机与生产任务 | 本次只改变可视化文案与映射；如需新阶段，另立后端任务编排设计。 |
| 新列表复制完整文档管理功能 | 代码重复、维护成本上升、权限入口混乱 | 列表只承担搜索、状态、Chunk、详情跳转；编辑权限、分类、删除继续留在文档管理页。 |
| Playwright 生成截图覆盖未提交文件 | 用户现有验收成果丢失 | T-001/T-010 中先备份，再更新；不使用强制恢复命令。 |
| 聚合接口在大数据量下变慢 | 页面首次加载延迟 | 使用 SQL `COUNT`/`SUM` 和现有文档索引；如监控发现瓶颈，再单独设计缓存，不在本次预先引入缓存。 |

## Rollout Checkpoints

1. **Checkpoint A — 后端合约完成**：summary 测试通过，OpenAPI 已更新，接口返回正确 camelCase 字段。
2. **Checkpoint B — 页面骨架完成**：页面头、指标、任务构建器和流水线可独立渲染；旧上传请求未变化。
3. **Checkpoint C — 工作台列表完成**：列表可搜索、刷新、分页、跳转详情；上传后可刷新数据。
4. **Checkpoint D — 自动化验收完成**：T09 mock 和断言更新，截图已在备份后生成。
5. **Checkpoint E — 发布准备完成**：验证矩阵全部通过；现有“文档管理”与导入任务测试无回归；Decision Log 无未决的阻塞决策。

## Progress Log

| 时间 | 任务 | 状态 | 证据/备注 |
| --- | --- | --- | --- |
| 2026-08-01 | T-001 | Completed | 保留主工作区的既有未提交改动；在 `C:\Users\xing\.config\superpowers\worktrees\lingxi\feat-doc-parsing-center-ui-refactor` 创建隔离 worktree，分支 `feat/doc-parsing-center-ui-refactor` 已跟踪并推送至 `origin`；计划文档已作为 `9ca348e` 提交。 |
| 2026-08-01 | T-002 | Completed | 新增 `test_document_summary_returns_visible_document_and_chunk_totals`；实现前请求 `/api/v1/documents/summary` 返回 404（红灯），实现后 summary 用例与完整 documents API 测试通过。 |
| 2026-08-01 | T-003 | Completed | 新增遵循 `DOCUMENT_READ` 权限边界的 `/api/v1/documents/summary`，按当前用户可见、未删除文档聚合已同步文档数和 Chunk 数。 |
| 2026-08-01 | T-004 | Completed | 已运行 `python -m server.scripts.export_openapi` 与 `npm run gen:api`，更新 OpenAPI、前端 schema 和 summary API 客户端；`npm run typecheck` 通过。 |
| 2026-08-01 | T-005 | Completed | `KnowledgePage` 已改为“文档解析与知识提炼中心”工作台，首次并行加载 summary 和第一页文档；上传/任务完成后刷新数据。 |
| 2026-08-01 | T-006 | Completed | 上传表单重排为文件、默认智能切分、分类、全员访问、范围 ID、构建任务；保留文件校验、分类和访问范围校验，title 自动取文件名。 |
| 2026-08-01 | T-007 | Completed | 流水线改为 `PARSING → QA_SPLITTING → EMBEDDING → COMPLETED` 四步，支持空闲、排队、失败、重试和进度展示；未引入不存在的 `INDEXING`。 |
| 2026-08-01 | T-008 | Completed | 新增紧凑文档处理列表，包含搜索、刷新、分页、分类空间、Chunk 数、状态和详情入口。 |
| 2026-08-01 | T-009 | Completed | 新增隔离 CSS 命名空间与响应式布局；发现 1024px 时顶部指标和工作区最小宽度导致根节点横向溢出，已用 861–1080px 中间断点改为纵向头部/单列工作区，并新增回归验收。 |
| 2026-08-01 | T-010 | Completed | 更新 `t09_knowledge_playwright.py`：mock summary、搜索、空闲/失败/完成流水线、表单顺序/禁用、刷新请求和 1024px smoke；先将验收截图备份到 `C:\Users\xing\AppData\Local\Temp\lingxi-t09-backup-20260802031139`，随后 Playwright 验收通过并更新 feature worktree 内截图。 |
| 2026-08-01 | T-011 | Completed | `python -m pytest server/tests/test_knowledge_documents_api.py -v`（9 passed）；`python -m pytest server/tests/test_import_jobs.py -v`（9 passed）；`npm run typecheck` 和 `npm run build`（均退出码 0，正确工作目录 `web/admin`）；`python web/admin/tests/t09_knowledge_playwright.py`（退出码 0）。额外以 Playwright 检查 1440/1024/768/320px：无意外横向溢出、每个视口检测到 17 个主交互控件且 Tab 焦点可达原生交互元素。一次合并命令曾在仓库根目录运行 npm，因不存在根 `package.json` 出现 ENOENT；未修改代码，随后在 `web/admin` 正确目录重跑并通过。 |

## Open Questions

1. 是否要在本期暴露真实可编辑的 Chunk Size 和 Chunk Overlap？当前 `DocumentUploadPanel` 传递的是固定 `processingOptions`，没有与参考图滑块等价、已生效的 `parseOptions` 后端契约。默认决策：本期只展示准确的默认智能切分说明，不提供不会生效的控件。
2. 第四步流水线是否必须逐字使用“QA 质检与问答对生成”？当前真实 QA 生成发生在 `QA_SPLITTING`，在向量化前。默认决策：采用真实顺序的“完成上架，可检索使用”；若要求新增 QA 质检阶段，需要单独设计 Worker 编排变更。
3. 文档处理列表是否需要展示失败任务的“重试”按钮？当前重试接口以 import job ID 为输入，文档列表虽有 `latestJob`，但解析中心本期可先提供详情入口。默认决策：本期展示详情/切片预览，不新增列表内重试操作。
4. 手工文档标题是否保留在“高级选项”中？默认决策：使用文件名自动生成 title，移除主视觉标题输入，保证参考布局更简洁。

## Decision Log

| ID | 日期 | 决策 | 理由 | 后果 |
| --- | --- | --- | --- | --- |
| D-001 | 2026-08-01 | 为解析中心新增 `/api/v1/documents/summary`，不复用 dashboard summary。 | 页面权限是 `DOCUMENT_READ`，dashboard 需要 `DASHBOARD_READ`。 | 新增小型 schema/repository/service/API/测试改动。 |
| D-002 | 2026-08-01 | summary 按当前用户可见文档统计。 | 顶部数字不能泄露未授权文档数量或 Chunk 数。 | repository 必须复用访问控制过滤。 |
| D-003 | 2026-08-01 | 不在 UI 中显示 `INDEXING`。 | 后端没有该任务阶段。 | 流水线与真实 Worker 状态一致。 |
| D-004 | 2026-08-01 | 本次不改变 QA 与 Embedding 的 Worker 顺序。 | 该变更会扩大为任务编排和重试语义重构。 | 第四步使用完成/上架语义而非伪造 QA 后置阶段。 |
| D-005 | 2026-08-01 | 解析中心新增轻量文档处理列表，不替换完整文档管理页。 | 避免复制批量归类、权限编辑、删除等复杂管理能力。 | 页面只提供搜索、状态、Chunk 和详情入口。 |
| D-006 | 2026-08-01 | 本期不新增无后端契约支持的 Chunk Size/Overlap 滑块。 | 不可保存或不可生效的控件会误导用户。 | 用默认智能切分说明替代。 |
| D-007 | 2026-08-01 | 在 861–1080px 中间断点将解析中心头部改为纵向、工作区改为单列。 | 自动化验收复现 1024px 根节点横向溢出：侧栏、内容内边距、指标最小宽度和双列工作区共同超出可用宽度。 | 1440px 保持左窄右宽；1024px、768px、320px 无意外横向溢出。 |
| D-008 | 2026-08-01 | Playwright 验收涵盖 summary、空闲/失败/完成流水线和 1024px 视口。 | 新页面的主要风险是 API 刷新遗漏、阶段伪造、访问控制排布和中等屏幕溢出。 | 回归脚本会验证上述主路径和布局边界。 |
