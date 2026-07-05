from collections.abc import Iterator
import json

from server.app.integrations.model_providers.base import (
    ConnectionTestResult,
    HttpProvider,
    ProviderError,
)


class OllamaProvider(HttpProvider):
    """Adapter for a native Ollama server (``base_url`` e.g. http://host:11434)."""

    provider_name = "ollama"

    def test_connection(self) -> ConnectionTestResult:
        try:
            self._request_json("GET", self._endpoint("/api/tags"), headers=self._headers())
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
        payload = self._chat_payload(prompt, stream=False)
        data = self._request_json(
            "POST", self._endpoint("/api/chat"), headers=self._headers(), json_body=payload
        )
        message = data.get("message") if isinstance(data, dict) else None
        content = (message or {}).get("content")
        if not isinstance(content, str):
            raise ProviderError("PROVIDER_BAD_RESPONSE", "Ollama 响应缺少文本内容")
        return content

    def generate_qa_pairs(self, prompt: str) -> str:
        return self.complete_chat(prompt)

    def stream_chat(self, prompt: str) -> Iterator[str]:
        payload = self._chat_payload(prompt, stream=True)
        for line in self._stream_lines(
            self._endpoint("/api/chat"), headers=self._headers(), json_body=payload
        ):
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (event.get("message") or {}).get("content")
            if content:
                yield content

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            data = self._request_json(
                "POST",
                self._endpoint("/api/embeddings"),
                headers=self._headers(),
                json_body={"model": self._require_model(), "prompt": text},
            )
            embedding = data.get("embedding") if isinstance(data, dict) else None
            if not isinstance(embedding, list):
                raise ProviderError("PROVIDER_BAD_RESPONSE", "Ollama Embedding 响应不合法")
            vectors.append(list(embedding))
        return vectors

    def _chat_payload(self, prompt: str, *, stream: bool) -> dict:
        return {
            "model": self._require_model(),
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }
