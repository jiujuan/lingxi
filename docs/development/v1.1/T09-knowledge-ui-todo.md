# T09 知识库中心 UI 闭环

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P0
- 预计范围：中

## Task 目标

实现知识库中心的前端可用闭环，让知识库管理员可以在 Web UI 中完成文档列表查看、上传、任务状态追踪、文档详情、QA 对查看、权限编辑和失败重试。

## 实现功能

- 知识库中心路由和页面框架。
- 文档列表：关键词、类型、状态、部门、角色、更新时间筛选。
- 文档列表分页、刷新、空状态、错误状态。
- 上传文档抽屉或页面：文件选择、拖拽上传、类型和大小校验。
- 上传前权限选择：部门、角色、用户、全部登录用户。
- 创建导入任务、上传或绑定文件、任务状态轮询。
- 文档处理阶段展示：上传中、解析中、QA 拆分中、向量化中、可问答、失败。
- 文档详情：元数据、权限范围、状态、原文片段、QA 对、处理日志。
- QA 对列表：问题、答案、页码、原文片段、Embedding 状态。
- 权限编辑弹窗，保存前二次确认。
- 失败任务重试入口，支持解析、QA 拆分、Embedding 阶段重试。
- 删除文档二次确认。
- 桌面和移动宽度下的基础响应式布局。

## 修改或增加文件

- `server/app/api/v1/documents.py`
- `server/app/api/v1/import_jobs.py`
- `server/app/repositories/document_repo.py`
- `server/app/schemas/document.py`
- `server/app/schemas/import_job.py`
- `server/app/services/document_center_service.py`
- `server/app/services/import_service.py`
- `server/tests/test_knowledge_documents_api.py`
- `web/admin/src/features/knowledge/pages/KnowledgePage.tsx`
- `web/admin/src/features/knowledge/pages/ImportPage.tsx`
- `web/admin/src/features/knowledge/api/documentApi.ts`
- `web/admin/src/features/knowledge/api/importJobApi.ts`
- `web/admin/src/features/knowledge/components/DocumentList.tsx`
- `web/admin/src/features/knowledge/components/DocumentUploadPanel.tsx`
- `web/admin/src/features/knowledge/components/DocumentDetailPanel.tsx`
- `web/admin/src/features/knowledge/components/DocumentPermissionModal.tsx`
- `web/admin/src/features/knowledge/components/QaPairList.tsx`
- `web/admin/src/features/knowledge/components/ImportJobTimeline.tsx`
- `web/admin/src/styles.css`

## 不修改范围

- 不实现后端文档解析、QA 拆分、Embedding 算法。
- 不实现混合检索和 Chat 回答。
- 不实现批量上传目录或拖拽文件夹。
- 不实现在线富文档编辑。
- 不绕过后端权限校验，前端权限仅用于体验展示。

## 涉及其它 Task

- 依赖 T05 提供上传任务和任务状态 API。
- 依赖 T08 提供 READY、Embedding 失败和 QA 对状态。
- 使用 T02 的当前用户、权限码和角色信息。
- T11 使用本任务建立的前端布局和错误提示模式。
- T15 复用任务日志入口和 request_id 展示规则。

## 测试策略

- 使用 mock API 测试文档列表筛选、分页、空状态和错误状态。
- 使用 mock API 测试上传前文件类型、大小、权限必填校验。
- 使用 fake timer 测试任务轮询停止条件。
- 测试失败任务的重试按钮和二次确认。
- 测试权限不足时操作按钮隐藏或禁用。
- Playwright 验证桌面宽度下上传到任务状态展示流程。
- Playwright 验证移动宽度下列表、上传抽屉、详情页不重叠。

## 长任务链路验收策略

使用一个样本文档从 UI 创建导入任务，完成文件上传或绑定，前端轮询任务状态，任务进入 READY 后进入文档详情，确认 QA 对、原文片段、权限范围和处理日志可见；模拟 QA/Embedding 失败时能展示失败阶段、错误摘要、request_id 和重试入口。

## 验收功能清单

- [x] 知识库中心路由可访问。
- [x] 文档列表可搜索、筛选、分页和刷新。
- [x] 上传前能校验文件类型、大小和权限范围。
- [x] 上传后能创建导入任务并展示任务进度。
- [x] 任务完成后文档可进入详情页查看。
- [x] 文档详情能展示原文片段、QA 对、权限范围和处理日志。
- [x] 失败状态能展示失败阶段、错误码、错误摘要和重试入口。
- [x] 权限编辑保存前有二次确认。
- [x] 删除文档有二次确认。
- [x] 桌面和移动宽度下核心 UI 无明显重叠。

## 验收结果

- 已实现知识库中心 UI 闭环：
  - 后端新增文档列表、详情、原文片段、权限更新、删除和导入任务重试接口。
  - 文档读取按租户、系统管理员和文档访问规则过滤；权限变更和删除写入审计日志。
  - 前端知识库中心支持上传、任务轮询、列表筛选、详情查看、QA 查看、权限弹窗、失败重试和删除二次确认。
  - 移动宽度下列表、筛选、上传、详情自动降为单栏布局。
- 验证证据：
  - `python -m pytest server\tests\test_knowledge_documents_api.py`：3 passed。
  - `python -m pytest server\tests`：37 passed。
  - `npm run build`（`web/admin`）：Vite build 成功。
  - `http://127.0.0.1:5174/#knowledge`：本地 Vite dev server HTTP 200，`5173` 已被占用所以改用 `5174`。
  - `python web\admin\tests\t09_knowledge_playwright.py`：Playwright Chromium 验收通过。
  - 截图证据：
    - `docs/development/v1.1/acceptance/t09-knowledge-desktop.png`
    - `docs/development/v1.1/acceptance/t09-knowledge-mobile.png`
- 浏览器验收覆盖：
  - 桌面视口 `1440x900` 和移动视口 `390x844`。
  - 知识库中心页面标题、文档列表、详情区、原文片段、QA 对、处理日志可见。
  - 权限弹窗可打开和关闭。
  - 失败文档可展示失败阶段、错误码、错误摘要，并可触发重试确认。
  - 页面和关键容器无水平溢出，浏览器控制台无 error/warning。

## 完成任务进度

100%
