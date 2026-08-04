from collections.abc import Iterator
import json

from server.app.integrations.model_providers.base import (
    ConnectionTestResult,
    HttpProvider,
    ProviderError,
)


class OpenAICompatibleProvider(HttpProvider):
    """Adapter for any OpenAI-compatible Chat Completions + Embeddings API.

    ``base_url`` should include the API version segment, e.g.
    ``https://api.openai.com/v1``. Endpoint paths are overridable via config
    (``chatPath`` / ``embeddingPath`` / ``modelsPath``).
    """

    provider_name = "openai_compatible"
    provider_type = "OPENAI_COMPATIBLE"

    @property
    def _chat_path(self) -> str:
        return self.config.get("chatPath") or "/chat/completions"

    @property
    def _embedding_path(self) -> str:
        return self.config.get("embeddingPath") or "/embeddings"

    @property
    def _models_path(self) -> str:
        return self.config.get("modelsPath") or "/models"

    def test_connection(self) -> ConnectionTestResult:
        try:
            self._request_json(
                "GET", self._endpoint(self._models_path), headers=self._headers()
            )
        except ProviderError as exc:
            return ConnectionTestResult.from_provider_error(exc)
        return ConnectionTestResult(
            success=True,
            status="SUCCESS",
            latency_ms=1,
            provider_name=self.provider_display_name,
            provider_type=self.provider_type,
            model_name=self.model_name,
            endpoint=self.last_endpoint,
            timeout_ms=self.timeout_ms,
        )

    def complete_chat(self, prompt: str) -> str:
        return self._post_chat(self._chat_payload(prompt, stream=False))

    def generate_qa_pairs(self, prompt: str) -> str:
        payload = self._chat_payload(prompt, stream=False)
        # Constrain the model to a strict JSON object so a chatty model can't
        # wrap the result in prose or ```json fences and break QA-split parsing.
        # Mirrors the Ollama adapter's format="json"; the response_format field
        # is honoured by OpenAI, DeepSeek, DashScope (Qwen) and Moonshot
        # compatible endpoints.
        payload["response_format"] = {"type": "json_object"}
        return self._post_chat(payload)

    def _post_chat(self, payload: dict) -> str:
        data = self._request_json(
            "POST",
            self._endpoint(self._chat_path),
            headers=self._headers(),
            json_body=payload,
            timeout_phase="inference",
        )
        return self._extract_message(data)

    def stream_chat(self, prompt: str) -> Iterator[str]:
        payload = self._chat_payload(prompt, stream=True)
        for line in self._stream_lines(
            self._endpoint(self._chat_path),
            headers=self._headers(),
            json_body=payload,
            timeout_phase="inference",
        ):
            for delta in self._parse_sse_deltas(line):
                if delta:
                    yield delta

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        payload: dict = {"model": self._require_model(), "input": texts}
        data = self._request_json(
            "POST",
            self._endpoint(self._embedding_path),
            headers=self._headers(),
            json_body=payload,
            timeout_phase="inference",
        )
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list) or len(items) != len(texts):
            raise ProviderError(
                "PROVIDER_BAD_RESPONSE",
                "Embedding 响应结构不合法",
                **self._provider_error_context(
                    endpoint=self._endpoint(self._embedding_path),
                ),
            )
        ordered = sorted(items, key=lambda item: item.get("index", 0))
        return [list(item.get("embedding") or []) for item in ordered]

    def _chat_payload(self, prompt: str, *, stream: bool) -> dict:
        payload: dict = {
            "model": self._require_model(),
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }
        max_tokens = self.config.get("maxTokens") or self.config.get("max_tokens")
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        temperature = self.config.get("temperature")
        if temperature is not None:
            payload["temperature"] = float(temperature)
        return payload

    def _extract_message(self, data: dict) -> str:
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:
            raise ProviderError(
                "PROVIDER_BAD_RESPONSE",
                "模型响应缺少 choices",
                **self._provider_error_context(
                    endpoint=self._endpoint(self._chat_path),
                ),
            )
        finish_reason = choices[0].get("finish_reason")
        if finish_reason == "length":
            raise ProviderError(
                "PROVIDER_OUTPUT_TRUNCATED",
                "模型输出因达到 token 上限而截断",
                retryable=False,
                **self._provider_error_context(
                    endpoint=self._endpoint(self._chat_path)
                ),
            )
        message = choices[0].get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            raise ProviderError(
                "PROVIDER_BAD_RESPONSE",
                "模型响应缺少文本内容",
                **self._provider_error_context(
                    endpoint=self._endpoint(self._chat_path),
                ),
            )
        return content

    @staticmethod
    def _parse_sse_deltas(line: str) -> Iterator[str]:
        if not line.startswith("data:"):
            return
        data = line[len("data:") :].strip()
        if not data or data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return
        for choice in payload.get("choices", []):
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                yield content
