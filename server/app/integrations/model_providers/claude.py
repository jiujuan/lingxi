from collections.abc import Iterator
import json

from server.app.integrations.model_providers.base import (
    ConnectionTestResult,
    HttpProvider,
    ProviderError,
)


class ClaudeProvider(HttpProvider):
    """Adapter for the Anthropic Claude Messages API.

    Anthropic uses ``x-api-key`` + ``anthropic-version`` headers (not Bearer)
    and has no embeddings endpoint, so :meth:`embed_texts` is unsupported.
    """

    provider_name = "claude"
    _DEFAULT_BASE_URL = "https://api.anthropic.com"
    _DEFAULT_VERSION = "2023-06-01"

    def _endpoint(self, path: str) -> str:
        base = (self.base_url or self._DEFAULT_BASE_URL).rstrip("/")
        return f"{base}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self.config.get("anthropicVersion") or self._DEFAULT_VERSION,
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def test_connection(self) -> ConnectionTestResult:
        try:
            self._request_json("GET", self._endpoint("/v1/models"), headers=self._headers())
        except ProviderError as exc:
            return ConnectionTestResult(
                success=False,
                status="FAILED",
                latency_ms=1,
                error_code=exc.code,
                error_message=exc.message,
            )
        return ConnectionTestResult(success=True, status="SUCCESS", latency_ms=1)

    def complete_chat(self, prompt: str) -> str:
        data = self._request_json(
            "POST",
            self._endpoint("/v1/messages"),
            headers=self._headers(),
            json_body=self._message_payload(prompt, stream=False),
        )
        blocks = data.get("content") if isinstance(data, dict) else None
        if not isinstance(blocks, list):
            raise ProviderError("PROVIDER_BAD_RESPONSE", "Claude 响应缺少 content")
        text = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        if not text:
            raise ProviderError("PROVIDER_BAD_RESPONSE", "Claude 响应缺少文本内容")
        return text

    def generate_qa_pairs(self, prompt: str) -> str:
        return self.complete_chat(prompt)

    def stream_chat(self, prompt: str) -> Iterator[str]:
        for line in self._stream_lines(
            self._endpoint("/v1/messages"),
            headers=self._headers(),
            json_body=self._message_payload(prompt, stream=True),
        ):
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if not data:
                continue
            try:
                event = json.loads(data)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "content_block_delta":
                delta = event.get("delta") or {}
                if delta.get("type") == "text_delta" and delta.get("text"):
                    yield delta["text"]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise ProviderError(
            "PROVIDER_EMBEDDING_UNSUPPORTED",
            "Claude 不提供 Embedding 接口，请为 Embedding 能力配置其它供应商",
        )

    def _message_payload(self, prompt: str, *, stream: bool) -> dict:
        max_tokens = self.config.get("maxTokens") or self.config.get("max_tokens") or 1024
        return {
            "model": self._require_model(),
            "max_tokens": int(max_tokens),
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }
