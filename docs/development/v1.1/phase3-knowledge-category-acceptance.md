# 第三阶段知识库分类检索验收证据

日期：2026-07-29  
范围：Task 7「第三阶段端到端验收和回归测试」

## 覆盖说明

- 后端检索范围：`RetrievalAccessScope` 的空间 / 部门 / 分类过滤与文档访问权限组合回归。
- 聊天接口：聊天 SSE 请求携带分类检索范围，QueryRun 记录检索范围，同一问题切换分类后不会继续引用原分类文档。
- 引用与解释：引用源、引用卡片、检索解释展示分类路径并保持权限校验。
- 分类运营：统计 API、未分类筛选、批量归类、删除保护、文档迁移接口回归。
- 前端验收：知识库分类管理 / 文档批量归类与迁移、聊天检索范围、引用与检索解释 Playwright 用例更新截图证据。

## 自动化验证结果

| 命令 | 结果 |
| --- | --- |
| `.\.venv\Scripts\python.exe -m pytest server/tests/test_retrieval_repo.py server/tests/test_retrieval_service.py -q` | 13 passed |
| `.\.venv\Scripts\python.exe -m pytest server/tests/test_chat_sse.py server/tests/test_citations_and_explanation.py -q` | 15 passed，1 个 Starlette/httpx deprecation warning |
| `.\.venv\Scripts\python.exe -m pytest server/tests/test_knowledge_classification.py server/tests/test_knowledge_documents_api.py server/tests/test_document_permissions.py -q` | 33 passed，Starlette/httpx 与 Alembic deprecation warnings |
| `npm run typecheck`（`web/admin`） | passed |
| `npm run lint`（`web/admin`） | 0 errors，6 个既有 React Hook warnings |
| `npm run build`（`web/admin`） | passed，Vite production build 完成 |
| `python web/admin/tests/t09_knowledge_playwright.py` | passed，更新知识库分类 / 文档验收截图 |
| `python web/admin/tests/t11_chat_playwright.py` | passed，更新聊天验收截图 |
| `python web/admin/tests/t12_citation_explanation_playwright.py` | passed，更新引用与检索解释验收截图 |

## 关键端到端证据

- `server/tests/test_chat_sse.py::test_chat_category_scope_switch_keeps_same_question_inside_selected_category`：真实 TestClient API + SSE 链路验证同一问题在「退款专题」可引用 `Refund SOP`，切换到 `cat-invoice` 后响应和落库引用均不再包含 `Refund SOP`，同时 QueryRun snapshot 记录 `scopeCategoryId=cat-invoice`。
- `docs/development/v1.1/acceptance/t09-knowledge-classification-desktop.png`：分类管理页展示统计数字、删除保护与迁移入口。
- `docs/development/v1.1/acceptance/t09-knowledge-documents-desktop.png`：文档列表展示未分类筛选、批量归类流程。
- `docs/development/v1.1/acceptance/t11-chat-desktop.png`、`docs/development/v1.1/acceptance/t11-chat-mobile.png`：聊天页检索范围选择与分类范围请求。
- `docs/development/v1.1/acceptance/t12-citation-desktop.png`：引用和检索解释展示分类路径。

## 验收 Checkpoint

- [x] 聊天 / 检索可按分类限定范围。
- [x] 分类过滤不绕过文档访问权限。
- [x] QueryRun 或 retrieval snapshot 能记录分类范围。
- [x] 引用和解释面板能展示分类路径。
- [x] 分类管理页能展示统计。
- [x] 文档列表支持未分类筛选和批量归类。
- [x] 分类删除保护和迁移流程可用。
- [x] 后端与前端主要回归测试通过。
