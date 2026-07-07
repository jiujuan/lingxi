from collections.abc import Iterator
from dataclasses import dataclass
import hashlib
import json
import time

import httpx


@dataclass(frozen=True)
class ConnectionTestResult:
    success: bool
    status: str
    latency_ms: int
    error_code: str | None = None
    error_message: str | None = None


class ProviderError(Exception):
    """Normalised error raised by real model providers.

    ``retryable`` lets task/service layers decide whether a retry could help
    (network blips, 429, 5xx) versus permanent failures (bad request, auth).
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.status_code = status_code


class ChatProvider:
    def test_connection(self) -> ConnectionTestResult:
        raise NotImplementedError

    def generate_qa_pairs(self, prompt: str) -> str:
        raise NotImplementedError

    def complete_chat(self, prompt: str) -> str:
        raise NotImplementedError

    def stream_chat(self, prompt: str) -> Iterator[str]:
        raise NotImplementedError


class EmbeddingProvider:
    dimension: int | None = None

    def test_connection(self) -> ConnectionTestResult:
        raise NotImplementedError

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


class BaseProvider(ChatProvider, EmbeddingProvider):
    """Shared configuration surface for every provider adapter."""

    provider_name = "base"

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        config: dict | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.config = config or {}

    @property
    def model_name(self) -> str | None:
        return self.config.get("modelName") or self.config.get("model")

    @property
    def timeout_seconds(self) -> float:
        raw = (
            self.config.get("timeoutMs")
            or self.config.get("timeout_ms")
            or 30000
        )
        try:
            return max(1.0, float(raw) / 1000)
        except (TypeError, ValueError):
            return 30.0

    @property
    def max_retries(self) -> int:
        try:
            return max(0, int(self.config.get("maxRetries", 2)))
        except (TypeError, ValueError):
            return 2


class HttpProvider(BaseProvider):
    """Base class for providers that call a real HTTP model API.

    Provides a shared httpx client factory, retry-with-backoff for transient
    failures, and consistent error normalisation to :class:`ProviderError`.
    """

    #: retry only on these HTTP status codes
    _RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}

    def _endpoint(self, path: str) -> str:
        base = (self.base_url or "").rstrip("/")
        if not base:
            raise ProviderError(
                "MISSING_PROVIDER_CONFIG", "模型供应商未配置 base_url"
            )
        if not path:
            return base
        return f"{base}/{path.lstrip('/')}"

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict | None = None,
    ) -> dict:
        last_error: ProviderError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.request(
                        method, url, headers=headers, json=json_body
                    )
                if response.status_code in self._RETRYABLE_STATUS:
                    last_error = self._status_error(response)
                    if attempt < self.max_retries:
                        self._sleep_backoff(attempt)
                        continue
                    raise last_error
                if response.status_code >= 400:
                    raise self._status_error(response)
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = ProviderError(
                    "PROVIDER_CONNECTION_ERROR",
                    f"模型供应商连接失败：{exc}",
                    retryable=True,
                )
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise last_error from exc
        # Unreachable, but keeps type-checkers satisfied.
        raise last_error or ProviderError(
            "PROVIDER_UNAVAILABLE", "模型供应商不可用", retryable=True
        )

    def _stream_lines(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        json_body: dict | None = None,
    ) -> Iterator[str]:
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                with client.stream(
                    "POST", url, headers=headers, json=json_body
                ) as response:
                    if response.status_code >= 400:
                        response.read()
                        raise self._status_error(response)
                    for line in response.iter_lines():
                        if line:
                            yield line
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise ProviderError(
                "PROVIDER_CONNECTION_ERROR",
                f"模型供应商流式连接失败：{exc}",
                retryable=True,
            ) from exc

    def _status_error(self, response: httpx.Response) -> ProviderError:
        retryable = response.status_code in self._RETRYABLE_STATUS
        code = "PROVIDER_SERVER_ERROR" if response.status_code >= 500 else "PROVIDER_REQUEST_ERROR"
        if response.status_code in (401, 403):
            code = "PROVIDER_UNAUTHORIZED"
        elif response.status_code == 429:
            code = "PROVIDER_RATE_LIMITED"
        message = self._extract_error_message(response)
        return ProviderError(
            code, message, retryable=retryable, status_code=response.status_code
        )

    @staticmethod
    def _extract_error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return f"模型供应商返回错误 HTTP {response.status_code}"
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and error.get("message"):
            return str(error["message"])
        if isinstance(error, str):
            return error
        if isinstance(payload, dict) and payload.get("message"):
            return str(payload["message"])
        return f"模型供应商返回错误 HTTP {response.status_code}"

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        # 0.5s, 1s, 2s, ... capped at 8s
        time.sleep(min(8.0, 0.5 * (2**attempt)))

    def _require_model(self) -> str:
        if not self.model_name:
            raise ProviderError(
                "MISSING_PROVIDER_CONFIG", "模型供应商未配置 model 名称"
            )
        return self.model_name


class MockProvider(BaseProvider):
    """Deterministic in-process provider used by tests and local dev.

    Selected by the registry when the configuration signals mock mode
    (``mock://`` base_url, explicit fixtures, or an empty base_url). It never
    performs network I/O so the test suite stays hermetic.
    """

    provider_name = "mock"

    def test_connection(self) -> ConnectionTestResult:
        if self.base_url == "mock://success":
            return ConnectionTestResult(success=True, status="SUCCESS", latency_ms=1)
        if self.base_url == "mock://failure":
            return ConnectionTestResult(
                success=False,
                status="FAILED",
                latency_ms=1,
                error_code="PROVIDER_UNAVAILABLE",
                error_message="模型供应商连接失败",
            )
        if self.config.get("testMode") == "failure":
            return ConnectionTestResult(
                success=False,
                status="FAILED",
                latency_ms=1,
                error_code="PROVIDER_UNAVAILABLE",
                error_message="模型供应商连接失败",
            )
        if self.base_url or self.api_key:
            return ConnectionTestResult(success=True, status="SUCCESS", latency_ms=1)
        return ConnectionTestResult(
            success=False,
            status="FAILED",
            latency_ms=1,
            error_code="MISSING_PROVIDER_CONFIG",
            error_message="模型供应商配置不完整",
        )

    def generate_qa_pairs(self, prompt: str) -> str:
        configured = self.config.get("qaSplitResponse")
        if configured is not None:
            return configured if isinstance(configured, str) else json.dumps(configured)

        return json.dumps(
            {
                "items": [
                    {
                        "question": "这段内容的核心问题是什么？",
                        "answer": prompt[:200],
                        "quote": prompt[:120],
                        "pageNo": 1,
                        "chunkIndex": 0,
                    }
                ]
            },
            ensure_ascii=False,
        )

    def complete_chat(self, prompt: str) -> str:
        if self.config.get("chatError"):
            raise RuntimeError(str(self.config["chatError"]))
        configured = self.config.get("chatResponse")
        if configured is not None:
            return str(configured)
        if "知识库中没有找到足够可靠的信息" in prompt:
            return "知识库中没有找到足够可靠的信息，无法根据现有资料回答。"
        return "根据知识库资料，" + prompt.split("用户问题：", 1)[-1].split("\n", 1)[0]

    def stream_chat(self, prompt: str) -> Iterator[str]:
        answer = self.complete_chat(prompt)
        chunk_size = int(self.config.get("chatChunkSize") or 8)
        for index in range(0, len(answer), chunk_size):
            yield answer[index : index + chunk_size]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        from server.app.core.config import settings

        dimension = int(
            self.config.get("embeddingDimension")
            or self.dimension
            or settings.embedding_vector_dimension
        )
        vectors: list[list[float]] = []
        for text in texts:
            seed = hashlib.sha256(text.encode("utf-8")).digest()
            vector = []
            for index in range(dimension):
                value = seed[index % len(seed)] / 255
                vector.append(round(value, 6))
            vectors.append(vector)
        return vectors


# Backwards-compatible alias: historically the mock was the only provider.
ConfiguredProvider = MockProvider
