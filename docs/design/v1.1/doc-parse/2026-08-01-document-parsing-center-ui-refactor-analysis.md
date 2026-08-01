# 文档解析中心页面重构分析

## 1. 范围与目标

本次目标是将后台“文档解析中心”从当前的“上传表单 + 最近任务进度”双栏页面，重构为参考图所示的文档解析工作台。重构范围包括：

- 顶部标题、说明和同步统计指标；
- 左侧“一键构建解析任务”卡片；
- 右侧“任务处理流水线”卡片；
- 下方正在解析/已同步文档列表；
- 响应式布局、空状态、错误状态和无障碍语义；
- 为顶部统计补充最小化后端聚合接口。

本次不重排解析 Worker 的真实执行顺序，不修改数据库表结构，不改变已有导入、权限、分类、重试和文件上传接口的业务语义。

## 2. 目标页面定位

侧边栏“文档解析中心”对应 `#knowledge` 路由，渲染链路如下：

```text
#knowledge
  -> ImportPage
  -> KnowledgePage
  -> DocumentUploadPanel + ImportJobTimeline
```

相关文件：

- `web/admin/src/routes/index.tsx`：`#knowledge` 路由，名称为“文档解析中心”。
- `web/admin/src/features/knowledge/pages/ImportPage.tsx`：重导出 `KnowledgePage`。
- `web/admin/src/features/knowledge/pages/KnowledgePage.tsx`：页面装配、任务轮询和当前布局。
- `web/admin/src/features/knowledge/components/DocumentUploadPanel.tsx`：上传、分类、权限和导入任务创建。
- `web/admin/src/features/knowledge/components/ImportJobTimeline.tsx`：当前任务处理进度展示。
- `web/admin/src/styles.css`：共享布局与上传/时间轴样式。

独立的“文档管理”页对应 `#document-management`，其功能不能被本次页面重构替代：

- `web/admin/src/features/knowledge/pages/DocumentManagementPage.tsx`

## 3. 当前页面与参考布局的差异

### 3.1 页面骨架

当前 `KnowledgePage` 使用 `knowledge-grid`，左侧为完整上传表单，右侧为“最近任务”时间线。页面没有顶部统计，也没有解析中心内的文档列表。

目标布局应调整为：

1. 页面头：标题“文档解析与知识提炼中心”、说明文案、右侧“已同步文档”和“已解析 Chunks”指标；
2. 主工作区：左侧任务构建器、右侧四步处理流水线；
3. 下方：可搜索的紧凑文档处理列表；
4. 移动端：按页面头、任务构建器、流水线、文档列表的顺序单列展示。

### 3.2 上传与权限字段

`DocumentUploadPanel.tsx` 目前字段顺序为：文档标题、上传区、知识库分类、所有登录用户可访问、部门/角色/用户 ID、创建导入任务。

目标调整为：

1. 新文档解析接入标题和支持格式说明；
2. 拖拽/选择上传区；
3. 切分设置说明或现有处理策略说明；
4. 知识库分类；
5. 所有登录用户可访问；
6. 部门 ID、角色 ID、用户 ID；
7. “一键构建解析任务”提交按钮。

“所有登录用户可访问”需要位于知识库分类之下；三个 ID 输入框位于该开关之后且位于提交按钮之前。全员访问勾选时，三个 ID 输入框继续保持禁用；取消全员访问且三个范围均为空时，继续复用当前“至少选择一种访问范围”的校验。

当前手工文档标题不是参考图中的主视觉。后端在创建任务时需要 `title`，但前端可继续用文件名去扩展名作为默认标题，因此可将人工标题输入框降级或移除，不影响 API 合约。

### 3.3 任务处理流水线

当前 `ImportJobTimeline.tsx` 硬编码了：

```text
CREATED -> PARSING -> QA_SPLITTING -> EMBEDDING -> INDEXING -> COMPLETED
```

其中 `INDEXING` 并不存在于后端状态机，属于前端展示与真实状态不一致的问题。

真实后端阶段为：

```text
CREATED -> PARSING -> QA_SPLITTING -> EMBEDDING -> COMPLETED
```

关键状态写入位置：

- `server/app/services/import_service.py`：文件绑定后将任务设为 `PARSING`，进度为 10；失败重试阶段为 `PARSING`、`QA_SPLITTING` 或 `EMBEDDING`。
- `server/app/services/document_parse_service.py`：解析完成后切换为 `QA_SPLITTING`，进度为 40。
- `server/app/services/embedding_service.py`：向量化开始时切换为 `EMBEDDING`，进度至少为 75；完成后切换为 `COMPLETED`，进度 100。

参考图的第四步文案“QA 质检与问答对生成”与当前 Worker 顺序不匹配：当前 QA 生成位于 `QA_SPLITTING`，发生在向量化前。因此推荐使用与真实后端一致的四步展示：

1. 文档解析（`PARSING`）；
2. 知识切分与 QA 问答生成（`QA_SPLITTING`）；
3. 向量化与知识入库（`EMBEDDING`）；
4. 完成上架，可检索使用（`COMPLETED`）。

UI 只做阶段映射与视觉重构，不新增虚构阶段，也不改动 Worker 编排。

### 3.4 文档处理列表

解析中心当前没有文档列表，但已有可复用数据源：

- `GET /api/v1/documents`；
- 前端客户端：`web/admin/src/features/knowledge/api/documentApi.ts`；
- 后端路由：`server/app/api/v1/documents.py`；
- 后端服务：`server/app/services/document_center_service.py`；
- 后端仓储：`server/app/repositories/document_repo.py`。

“文档管理”页和“文档列表”页已有更完整的筛选、权限编辑、删除、批量归类等管理功能。解析中心应新增轻量工作台列表，不复制这些重型管理能力。建议展示：

- 文档名称、更新时间和文件大小；
- 知识分类空间；
- `chunkCount`；
- 解析/同步状态；
- 查看详情和切片预览入口。

列表搜索直接使用已有 `keyword` 查询参数，详情入口跳转已有 `#document-management-detail?documentId=<id>`。

### 3.5 顶部统计指标

参考图需显示“已同步文档”和“已解析 Chunks”。现有分页文档接口不能可靠求整个租户的总 Chunk 数；已有 dashboard summary 虽有文档数，但需要 `DASHBOARD_READ` 权限，不能让只拥有 `DOCUMENT_READ` 的解析中心用户依赖该权限。

建议新增：

```text
GET /api/v1/documents/summary
```

建议响应：

```json
{
  "syncedDocumentCount": 1248,
  "totalChunkCount": 84512
}
```

该聚合应复用文档列表的租户隔离、软删除过滤和访问范围逻辑：

- 仅当前租户；
- 排除 `deleted_at` 非空和 `DELETED` 文档；
- 非系统管理员仅汇总当前 `AccessContext` 有权访问的文档；
- 文档数为 `COUNT(Document.id)`；
- Chunk 总数为 `COALESCE(SUM(Document.chunk_count), 0)`。

`Document.chunk_count` 已由解析链路维护，因此无需迁移数据库或读取全部 Chunk 表。

## 4. 推荐组件职责

| 组件/模块 | 建议职责 |
| --- | --- |
| `KnowledgePage.tsx` | 页面装配、summary 与文档列表加载、任务轮询、上传成功后的统一刷新。 |
| `DocumentUploadPanel.tsx` | 仅负责构建导入请求、文件上传、分类和权限收集；通过回调通知父级任务已创建。 |
| `ImportJobTimeline.tsx` | 仅负责将任务状态映射为四步流水线、空闲/失败/完成视觉状态。 |
| `DocumentProcessingList.tsx`（新增） | 解析中心专用紧凑文档表格、关键词搜索、页面内刷新和详情跳转。 |
| `documentApi.ts` | 文档列表和 summary 请求的类型化封装。 |
| `DocumentRepository` / `DocumentCenterService` | 复用访问控制边界实现 summary 聚合。 |

## 5. 后端影响边界

需要修改：

- 文档 schema：新增 summary response；
- 文档 repository：新增可见文档数量与 Chunk 总数聚合；
- 文档 service：新增 summary 方法；
- documents API：增加 `GET /summary`；
- OpenAPI 及前端生成类型；
- 对应 API 测试。

不需要修改：

- 导入任务表、文档表、Chunk 表及 Alembic migration；
- 文件上传 API 与 multipart 行为；
- 任务队列、解析 Worker、QA Worker、Embedding Worker 的执行顺序；
- 原有“文档管理”页的权限编辑、分类、删除和分页功能。

## 6. 测试与验收影响

后端：

- `server/tests/test_knowledge_documents_api.py`：增加 summary 正确聚合、排除删除文档、租户隔离和访问可见性测试。
- `server/tests/test_import_jobs.py`：已有导入、分类和权限测试应继续通过，确保上传表单重排未改变请求载荷。

前端：

- `web/admin/tests/t09_knowledge_playwright.py`：更新页面标题、按钮名称、流水线状态、summary mock、上传完成后的列表/指标刷新断言。
- `web/admin/src/styles.css`：补齐桌面和小于 860px 的移动端单列样式。

现有工作区中已有未提交的相关验收截图：

- `docs/development/v1.1/acceptance/t09-knowledge-upload-desktop.png`
- `docs/development/v1.1/acceptance/t09-knowledge-desktop.png`
- `docs/development/v1.1/acceptance/t09-knowledge-mobile.png`

执行 Playwright 截图验收前必须保留或备份这些文件，避免覆盖用户已有变更。

## 7. 推荐实施边界

推荐按“页面重构 + 最小统计接口”交付：

- 后端只新增文档解析中心 summary，不改变业务状态机；
- 前端完全按参考图重构信息层级和视觉层级；
- 四步流水线以真实 Worker 阶段为准；
- 页面内新增轻量文档处理列表，保留独立“文档管理”页作为完整管理入口。