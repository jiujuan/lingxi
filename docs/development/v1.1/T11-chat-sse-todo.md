# T11 Web Chat SSE 流式问答

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P0
- 预计范围：中

## Task 目标

实现 Web Chat 的后端 API、SSE 流式输出和前端交互，让员工可以创建会话、提交问题、看到流式答案、拒答提示、引用事件和反馈入口。

## 实现功能

- Chat 会话列表、创建会话、消息列表 API。
- `POST /api/v1/chat/sessions/{sessionId}/message-runs` SSE 接口。
- SSE 事件：`run_started`、`delta`、`citation`、`done`、`error`。
- 用户问题和助手回答落库。
- 调用 T10 检索引擎获取候选。
- 强约束 Prompt 构造：只能根据参考资料回答，无答案必须拒答。
- 模型流式调用封装。
- 知识不足拒答分支，不生成虚假引用。
- 模型失败、超时和空回答处理。
- Chat 前端三栏布局：会话列表、消息流、引用区域。
- 输入框 Enter 发送、Shift+Enter 换行。
- 生成期间输入框禁用或排队提示。
- 回答复制、重试、点赞/点踩反馈入口。

## 修改或增加文件

- `server/app/api/routes/chat.py`
- `server/app/services/chat_service.py`
- `server/app/services/prompt_service.py`
- `server/app/services/sse_service.py`
- `server/app/repositories/chat_repository.py`
- `server/app/repositories/query_run_repository.py`
- `server/app/repositories/feedback_repository.py`
- `server/app/schemas/chat.py`
- `web/src/pages/chat/ChatPage.tsx`
- `web/src/pages/chat/ChatSessionList.tsx`
- `web/src/pages/chat/ChatMessageList.tsx`
- `web/src/pages/chat/ChatComposer.tsx`
- `web/src/pages/chat/CitationPanel.tsx`
- `web/src/api/chat.ts`
- `web/src/types/chat.ts`
- `server/app/tests/api/test_chat_sse.py`
- `server/app/tests/services/test_chat_service.py`
- `web/src/tests/e2e/chat-sse.spec.ts`

## 不修改范围

- 不实现 OpenAI 兼容 `/v1/chat/completions`。
- 不实现检索算法本身，只调用 T10 的检索服务。
- 不实现引用原文详情和检索解释完整 UI，该能力由 T12 完成。
- 不做多轮复杂记忆和长期用户画像。
- 不做 IM 渠道接入。

## 涉及其它 Task

- 依赖 T09 的前端布局、错误提示和权限展示模式。
- 依赖 T10 的检索候选、置信度和检索快照。
- 依赖 T04 的默认对话模型配置和模型调用 Adapter。
- T12 基于本任务的 run_id、message_id 和 citation 事件补全引用详情。
- T15 记录和展示本任务产生的模型调用日志、query_run 和 request_id。
- T17 验证 SSE 在代理和移动宽度下的稳定性。

## 测试策略

- 后端测试 SSE 正常事件顺序。
- 后端测试知识不足分支返回固定拒答文案且无 citation 事件。
- 后端测试模型超时、模型失败、空回答时返回 `error` 事件。
- 后端测试用户无权限文档不会进入 Prompt 或引用。
- 前端测试流式 delta 追加到同一条助手消息。
- 前端测试生成中禁止重复提交或展示排队提示。
- Playwright 使用 mock SSE 验证桌面和移动宽度 Chat 交互。

## 长任务链路验收策略

以员工身份进入 Chat，创建会话并提交一个有答案问题，观察 SSE 从 `run_started` 到 `done` 的完整事件链路，确认回答流式展示、至少一条引用出现、消息落库；再提交一个无答案问题，确认返回知识不足拒答且没有虚假引用。

## 验收功能清单

- [x] 会话列表、创建会话和消息列表 API 可用。
- [x] Chat SSE 接口返回标准事件。
- [x] 用户问题和助手回答能落库。
- [x] 有答案问题能流式输出回答。
- [x] 有答案回答至少产生 1 条引用事件。
- [x] 知识不足问题返回拒答文案且无虚假引用。
- [x] 模型失败时前端展示可重试错误和 request_id。
- [x] Chat 前端支持 Enter 发送、Shift+Enter 换行。
- [x] 生成中防止重复提交或明确排队。
- [x] 点赞/点踩反馈入口可记录。

## 验收结果

- 已完成。
- 后端验证：`python -m pytest server\tests`，结果 `45 passed`。
- 前端构建：`npm run build`，结果 Vite build 成功。
- 浏览器验收：`python web\admin\tests\t11_chat_playwright.py`，结果通过。
- 验收截图：
  - `docs/development/v1.1/acceptance/t11-chat-desktop.png`
  - `docs/development/v1.1/acceptance/t11-chat-mobile.png`

## 完成任务进度

100%
