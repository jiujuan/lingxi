# T14 OpenAI 兼容 Chat Completions API

## 任务状态

- 状态：DONE
- 完成任务进度：100%
- 优先级：P1
- 预计范围：中

## Task 目标

实现企业内部系统可直接调用的 OpenAI 兼容 `/v1/chat/completions` 接口，支持 API Key 认证、流式和非流式响应、知识库权限检索、拒答、引用扩展和 request_id。

## 实现功能

- `POST /v1/chat/completions` 路由。
- API Key Bearer 认证。
- Scope、状态、过期时间、限流校验。
- OpenAI messages 映射为内部 question。
- 非流式响应兼容 `chat.completion` 结构。
- 流式响应兼容 `chat.completion.chunk` 和 `[DONE]`。
- 扩展返回 `citations` 和 `request_id`。
- 使用 API Key 绑定的部门和角色权限范围执行检索。
- 调用 T10 检索引擎和 T04 模型网关。
- 知识不足时返回固定拒答文案。
- 错误响应兼容 OpenAI 风格，并保留内部 `request_id`。
- API 调用日志记录 path、status_code、latency_ms、error_code。
- README 或文档片段提供 curl 和 SDK 调用示例。

## 修改或增加文件

- `server/app/api/routes/openai_compatible.py`
- `server/app/services/openai_compatible_service.py`
- `server/app/schemas/openai_compatible.py`
- `server/app/services/api_chat_service.py`
- `server/app/core/openai_errors.py`
- `server/app/tests/api/test_openai_compatible_chat.py`
- `server/app/tests/api/test_openai_compatible_stream.py`
- `server/app/tests/security/test_openai_api_key_scope.py`
- `docs/development/v1.1/examples/openai-compatible-api.md`

## 不修改范围

- 不实现 OpenAI 的全部 API 面，包括 Assistants、Responses、Embeddings、Files。
- 不保证第三方 SDK 的所有高级参数都完整支持。
- 不返回无权限文档引用。
- 不支持 API Key 绕过 Web 用户权限体系。
- 不做 IM、Widget 或客服工单接入。

## 涉及其它 Task

- 依赖 T10 的检索引擎。
- 依赖 T13 的 API Key 认证、Scope、限流和调用日志。
- 依赖 T04 的模型供应商和默认对话模型。
- 复用 T11 的 Prompt 规则、知识不足拒答和模型流式能力。
- T15 展示本任务产生的 API 调用日志。
- T17 对标准客户端兼容性、越权和流式稳定性做验收。

## 测试策略

- 测试非流式响应结构兼容 OpenAI Chat Completions。
- 测试流式响应 chunk 和 `[DONE]`。
- 测试响应扩展 `citations` 和 `request_id` 不破坏标准字段。
- 测试无答案问题拒答且无虚假引用。
- 测试 API Key 无效、禁用、过期、Scope 不足、限流。
- 测试 API Key 权限范围不会召回无权文档。
- 测试 API 调用日志不记录 Authorization header。
- 使用 curl 样例做手工验收。

## 长任务链路验收策略

用系统管理员创建的 API Key 调用 `/v1/chat/completions`，分别验证 `stream=false` 和 `stream=true`。有答案问题返回标准 choices 和 citations；无答案问题返回拒答；禁用 Key 后调用返回 401；Scope 不足返回 403；调用日志可按 request_id 查到。

## 验收功能清单

- [x] `/v1/chat/completions` 路由可用。
- [x] API Key Bearer 认证可用。
- [x] 非流式响应兼容 OpenAI Chat Completions。
- [x] 流式响应兼容 chunk 和 `[DONE]`。
- [x] 响应包含 citations 和 request_id 扩展。
- [x] 知识不足问题明确拒答。
- [x] API Key 权限范围参与检索过滤。
- [x] 错误语义覆盖 401、403、429、503。
- [x] API 调用日志可查询。
- [x] 示例文档可按步骤完成调用。

## 验收结果

- 已完成。
- 后端定向验证：`python -m pytest server\tests\test_openai_compatible_api.py`，结果 `6 passed`。
- 全量后端验证：`python -m pytest server\tests`，结果 `55 passed`。
- 前端构建回归：`npm run build`，结果 Vite build 成功。
- 示例文档：`docs/development/v1.1/examples/openai-compatible-api.md`。

## 完成任务进度

100%
