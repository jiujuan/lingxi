# OpenAI 兼容 Chat Completions API 示例

## 前置条件

- 已在 Web 管理端创建 API Key。
- API Key Scope 包含 `chat:completions`。
- API Key 的部门或角色范围能访问目标知识库文档。

## 非流式调用

```bash
curl -s http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer lk_live_xxx" \
  -d '{
    "model": "knowledge-chat",
    "messages": [
      {"role": "user", "content": "退款需要谁审批？"}
    ],
    "stream": false
  }'
```

响应包含标准 `choices`，并扩展 `citations` 和 `request_id`。

## 流式调用

```bash
curl -N http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer lk_live_xxx" \
  -d '{
    "model": "knowledge-chat",
    "messages": [
      {"role": "user", "content": "退款需要谁审批？"}
    ],
    "stream": true
  }'
```

流式响应使用 `data:` 行输出 `chat.completion.chunk`，引用以扩展事件输出，最后返回：

```text
data: [DONE]
```

## 错误语义

- `401 INVALID_API_KEY`：Key 缺失、错误、禁用或过期。
- `403 API_KEY_FORBIDDEN`：Scope 不足。
- `429 RATE_LIMITED`：超过每分钟限流。
- `503 MODEL_UNAVAILABLE`：模型服务不可用。

API 调用日志只记录 key 前缀、状态码、耗时和 `request_id`，不会记录明文 Key 或 Authorization header。
