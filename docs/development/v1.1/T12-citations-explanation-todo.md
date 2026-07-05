# T12 引用原文与检索解释

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P0
- 预计范围：中

## Task 目标

补全可信回答的可追溯能力，让用户能点击引用查看原文片段、文档标题和页码，让管理员能按 run_id 查看向量召回、全文召回、RRF 和 ReRank 的检索解释。

## 实现功能

- 引用快照写入和读取。
- `GET /api/v1/query-runs/{runId}` 回答运行详情。
- `GET /api/v1/query-runs/{runId}/citations` 引用列表。
- `GET /api/v1/citations/{citationId}/source` 引用原文片段。
- `GET /api/v1/query-runs/{runId}/retrieval-explanation` 检索解释。
- 引用原文查看时按当前文档权限再次校验。
- 文档已删除时展示历史引用快照，不允许下载原文件。
- 普通员工只看到自己有权限的解释候选。
- 管理员在授权范围内查看完整检索解释。
- Chat 右侧引用面板展示文档标题、页码、quote、rank、score。
- 引用点击后定位或展开原文片段。
- 检索解释 UI 展示向量、全文、RRF、ReRank 四阶段。

## 修改或增加文件

- `server/app/api/routes/query_runs.py`
- `server/app/api/routes/citations.py`
- `server/app/services/citation_service.py`
- `server/app/services/retrieval_explanation_service.py`
- `server/app/repositories/citation_repository.py`
- `server/app/schemas/citation.py`
- `server/app/schemas/query_run.py`
- `web/src/pages/chat/CitationPanel.tsx`
- `web/src/pages/chat/CitationSourceDrawer.tsx`
- `web/src/pages/chat/RetrievalExplanationPanel.tsx`
- `web/src/api/citations.ts`
- `web/src/api/queryRuns.ts`
- `web/src/types/citation.ts`
- `server/app/tests/api/test_citations.py`
- `server/app/tests/api/test_retrieval_explanation.py`
- `web/src/tests/e2e/citation-source.spec.ts`

## 不修改范围

- 不重新实现 Chat SSE。
- 不重新实现检索排序算法。
- 不展示无权限候选的明细内容。
- 不实现 PDF 在线逐页渲染器，只展示 V1.1 需要的原文片段、页码和来源定位。
- 不提供历史引用绕过当前权限下载原文件的能力。

## 涉及其它 Task

- 依赖 T10 的检索快照结构。
- 依赖 T11 的 Chat run_id、message_id 和 citation 事件。
- 使用 T03 的 `query_runs`、`query_citations`、`documents`、`qa_pairs` 数据。
- T15 复用 run_id 和 retrieval snapshot 进入日志排障。
- T17 验证引用不越权、历史引用快照可解释。

## 测试策略

- 测试引用列表按 rank 排序。
- 测试引用原文查看需要当前用户有文档权限。
- 测试文档删除后仍可展示引用快照。
- 测试无权限用户访问引用原文返回 403。
- 测试检索解释只返回授权范围内候选。
- 前端测试点击引用打开原文抽屉。
- 前端测试检索解释四阶段展示和空状态。

## 长任务链路验收策略

完成一次有答案 Chat 后，从回答引用点击进入原文片段，确认标题、页码、quote、rank、score 正确；再切换为无权用户访问同一引用，确认引用快照和原文详情的权限边界符合设计；管理员按 run_id 打开检索解释，能看到四阶段候选和分数。

## 验收功能清单

- [x] 回答运行详情 API 可用。
- [x] 引用列表 API 可用并按 rank 排序。
- [x] 引用原文 API 按当前权限校验。
- [x] 文档删除后历史引用快照仍可解释。
- [x] 检索解释包含向量、全文、RRF、ReRank 四阶段。
- [x] 普通员工看不到无权限候选。
- [x] Chat 引用面板可点击打开原文片段。
- [x] 检索解释 UI 能展示候选分数和特征。
- [x] API 错误包含 request_id。
- [x] 引用内容不包含无权限文档。

## 验收结果

- 已完成。
- 后端验证：`python -m pytest server\tests`，结果 `49 passed`。
- 前端构建：`npm run build`，结果 Vite build 成功。
- 浏览器验收：`python web\admin\tests\t12_citation_explanation_playwright.py`，结果通过。
- 回归验收：`python web\admin\tests\t11_chat_playwright.py`，结果通过。
- 验收截图：
  - `docs/development/v1.1/acceptance/t12-citation-desktop.png`
  - `docs/development/v1.1/acceptance/t12-citation-mobile.png`

## 完成任务进度

100%
