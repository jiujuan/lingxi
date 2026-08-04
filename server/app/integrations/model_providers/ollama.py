from collections.abc import Iterator
import json

from server.app.integrations.model_providers.base import (
    ConnectionTestResult,
    HttpProvider,
    ProviderError,
)

_QA_SPLIT_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "question": {"type": "string"},
                    "answer": {"type": "string"},
                    "quote": {"type": "string"},
                    "pageNo": {"type": "integer", "minimum": 1},
                    "chunkIndex": {"type": "integer", "minimum": 0},
                },
                "required": [
                    "question",
                    "answer",
                    "quote",
                    "pageNo",
                    "chunkIndex",
                ],
            },
        },
        "coveredChunkIndexes": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
        },
        "skippedChunks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "chunkIndex": {"type": "integer", "minimum": 0},
                    "reason": {"type": "string"},
                },
                "required": ["chunkIndex", "reason"],
            },
        },
    },
    "required": ["items", "coveredChunkIndexes", "skippedChunks"],
}


class OllamaProvider(HttpProvider):
    """Adapter for a native Ollama server (``base_url`` e.g. http://host:11434)."""

    provider_name = "ollama"
    provider_type = "OLLAMA"

    def test_connection(self) -> ConnectionTestResult:
        try:
            self._request_json("GET", self._endpoint("/api/tags"), headers=self._headers())
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
        # JSON mode alone permits an empty object (Gemma can return "{}").
        # Ollama's schema-constrained format keeps the response aligned with
        # the provenance contract validated by QaSplitService.
        payload["format"] = _QA_SPLIT_OUTPUT_SCHEMA
        options = dict(payload.get("options") or {})
        options.setdefault("temperature", 0)
        payload["options"] = options
        return self._post_chat(payload)

    def _post_chat(self, payload: dict) -> str:
        data = self._request_json(
            "POST",
            self._endpoint("/api/chat"),
            headers=self._headers(),
            json_body=payload,
            timeout_phase="inference",
        )
        if isinstance(data, dict) and data.get("done_reason") == "length":
            raise ProviderError(
                "PROVIDER_OUTPUT_TRUNCATED",
                "模型输出因达到 token 上限而截断",
                retryable=False,
                **self._provider_error_context(
                    endpoint=self._endpoint("/api/chat")
                ),
            )
        message = data.get("message") if isinstance(data, dict) else None
        content = (message or {}).get("content")
        if not isinstance(content, str):
            raise ProviderError(
                "PROVIDER_BAD_RESPONSE",
                "Ollama 响应缺少文本内容",
                **self._provider_error_context(
                    endpoint=self._endpoint("/api/chat"),
                ),
            )
        return content

    def stream_chat(self, prompt: str) -> Iterator[str]:
        payload = self._chat_payload(prompt, stream=True)
        for line in self._stream_lines(
            self._endpoint("/api/chat"),
            headers=self._headers(),
            json_body=payload,
            timeout_phase="inference",
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
                timeout_phase="inference",
            )
            embedding = data.get("embedding") if isinstance(data, dict) else None
            if not isinstance(embedding, list):
                raise ProviderError(
                    "PROVIDER_BAD_RESPONSE",
                    "Ollama Embedding 响应不合法",
                    **self._provider_error_context(
                        endpoint=self._endpoint("/api/embeddings"),
                    ),
                )
            vectors.append(list(embedding))
        return vectors

    def _chat_payload(self, prompt: str, *, stream: bool) -> dict:
        payload = {
            "model": self._require_model(),
            "messages": [{"role": "user", "content": prompt}],
            "stream": stream,
        }
        max_tokens = self.config.get("maxTokens") or self.config.get("max_tokens")
        if max_tokens:
            payload["options"] = {"num_predict": int(max_tokens)}
        return payload
