上面完成了OpenAI兼容接口，如果不兼容OpenAI的chat接口，比如ollama、anthropic等等大模型呢，chat接口API是怎么处理


• 这里要分清两层接口：

  1. 对外暴露的 Chat API
    T14 做的是对外统一暴露 OpenAI 兼容接口：

  POST /v1/chat/completions

  这层是给内部系统、SDK、curl 调用的入口。即使底层模型是 Ollama、Anthropic、Claude、DeepSeek、自研网关，对外也可以保持这个接口不变。

  2. 对内调用大模型供应商的 Adapter
    真正处理 Ollama、Anthropic 这些“不兼容 OpenAI Chat API”的地方，不应该放在 /v1/chat/completions 路由里，而是放在模型适配器层。

  当前代码路径是：

  - server/app/services/openai_compatible_service.py
  - server/app/integrations/model_providers/registry.py
  - server/app/integrations/model_providers/openai_compatible.py
  - server/app/integrations/model_providers/ollama.py
  - server/app/integrations/model_providers/claude.py
  - server/app/integrations/model_providers/base.py

  处理方式是：

  外部请求 /v1/chat/completions
          ↓
  OpenAICompatibleService
          ↓
  内部统一 Prompt / Retrieval / Citation
          ↓
  build_provider_adapter(provider_type)
          ↓
  不同供应商 Adapter
          ↓
  OpenAI / Ollama / Anthropic / Claude / 内部网关

  也就是说，业务层只调用统一方法：

  adapter.complete_chat(prompt)
  adapter.stream_chat(prompt)

  至于底层到底是：

  - OpenAI：/v1/chat/completions
  - Ollama：/api/chat 或 /api/generate
  - Anthropic：/v1/messages
  - Claude：Anthropic Messages API
  - 内部网关：自定义接口

  都由对应 Adapter 自己转换。

  Ollama 示例

  Ollama 通常不是 OpenAI 原生格式，它的请求可能是：

  {
    "model": "qwen2.5",
    "messages": [
      {"role": "user", "content": "你好"}
    ],
    "stream": true
  }

  Adapter 里要做：

  内部 prompt/messages
  → Ollama /api/chat 请求格式
  → 读取 Ollama stream 行
  → 转成内部 delta 文本

  Anthropic 示例

  Anthropic Messages API 更不一样：

  {
    "model": "claude-3-5-sonnet",
    "max_tokens": 1024,
    "messages": [
      {
        "role": "user",
        "content": "你好"
      }
    ]
  }

  Header 也不同：

  x-api-key: ...
  anthropic-version: 2023-06-01

  Adapter 里要做：

  内部 prompt
  → Anthropic messages 格式
  → 处理 content_block_delta / message_delta 等事件
  → 转成内部 delta 文本

  关键原则

  不要为每个模型供应商改业务接口。

  正确做法是：

  Web Chat API
  OpenAI Compatible API
  OpenAI-Compatible external clients
          ↓
  统一进入内部 Chat / Retrieval / Prompt / Citation 流程
          ↓
  模型供应商差异只在 Adapter 层处理

  所以后续如果要真正支持 Ollama、Anthropic，需要补的是：

  - OllamaProvider.complete_chat()
  - OllamaProvider.stream_chat()
  - ClaudeProvider.complete_chat()
  - ClaudeProvider.stream_chat()
  - 对应连接测试、错误码映射、流式解析测试

  而不是新增一套业务 Chat API。

  如果要“兼容 Ollama 客户端”或“兼容 Anthropic 客户端”，那是另一类对外协议适配，比如：

  POST /api/chat             # Ollama 风格
  POST /v1/messages          # Anthropic 风格

  这属于新的兼容入口，不是 T14 的 OpenAI 兼容接口范围。当前架构支持以后扩展，但建议先把模型 Provider Adapter 做实。