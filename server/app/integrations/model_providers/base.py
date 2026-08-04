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
    provider_name: str | None = None
    provider_type: str | None = None
    model_name: str | None = None
    endpoint: str | None = None
    timeout_ms: int | None = None
    timeout_phase: str | None = None

    @classmethod
    def from_provider_error(
        cls, error: "ProviderError", *, latency_ms: int = 1
    ) -> "ConnectionTestResult":
        return cls(
            success=False,
            status="FAILED",
            latency_ms=latency_ms,
            error_code=error.code,
            error_message=error.message,
            provider_name=error.provider_name,
            provider_type=error.provider_type,
            model_name=error.model_name,
            endpoint=error.endpoint,
            timeout_ms=error.timeout_ms,
            timeout_phase=error.timeout_phase,
        )


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
        provider_name: str | None = None,
        provider_type: str | None = None,
        model_name: str | None = None,
        endpoint: str | None = None,
        timeout_ms: int | None = None,
        timeout_phase: str | None = None,
    ) -> None:
        self.base_message = message
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.provider_name = provider_name
        self.provider_type = provider_type
        self.model_name = model_name
        self.endpoint = endpoint
        self.timeout_ms = timeout_ms
        self.timeout_phase = timeout_phase
        self.message = self._format_message()
        super().__init__(self.message)

    def _format_message(self) -> str:
        details: list[str] = []
        if self.provider_name:
            details.append(f"供应商：{self.provider_name}")
        if self.model_name:
            details.append(f"模型：{self.model_name}")
        if self.provider_type:
            details.append(f"类型：{_display_provider_type(self.provider_type)}")
        if self.endpoint:
            details.append(f"endpoint：{self.endpoint}")
        if self.timeout_ms is not None and self.code in {
            "PROVIDER_CONNECTION_TIMEOUT",
            "PROVIDER_INFERENCE_TIMEOUT",
        }:
            timeout_label = _timeout_label(self.code, self.timeout_phase)
            details.append(f"超时：{self.timeout_ms // 1000} 秒{timeout_label}")
        if not details:
            return self.base_message
        return f"{self.base_message}（{'; '.join(details)}）"


def _display_provider_type(provider_type: str) -> str:
    labels = {
        "OPENAI_COMPATIBLE": "OpenAI Compatible",
        "INTERNAL_GATEWAY": "Internal Gateway",
        "OLLAMA": "Ollama",
        "CLAUDE": "Claude",
    }
    return labels.get(provider_type, provider_type)


def _timeout_label(code: str, timeout_phase: str | None) -> str:
    if code == "PROVIDER_INFERENCE_TIMEOUT":
        return "读取超时"
    if timeout_phase == "connect":
        return "连接超时"
    return "响应超时"


class ChatProvider:
    def test_connection(self) -> ConnectionTestResult:
        raise NotImplementedError

    def test_model_connection(self) -> ConnectionTestResult:
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
    provider_type = "BASE"

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        config: dict | None = None,
        *,
        provider_name: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.config = config or {}
        self.provider_display_name = provider_name or self.provider_name
        self.last_endpoint: str | None = None

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

    @property
    def timeout_ms(self) -> int:
        return max(1, int(self.timeout_seconds * 1000))

    def _provider_error_context(
        self,
        *,
        endpoint: str | None = None,
        timeout_phase: str | None = None,
    ) -> dict:
        return {
            "provider_name": self.provider_display_name,
            "provider_type": self.provider_type,
            "model_name": self.model_name,
            "endpoint": endpoint,
            "timeout_ms": self.timeout_ms,
            "timeout_phase": timeout_phase,
        }

    def test_model_connection(self) -> ConnectionTestResult:
        started = time.perf_counter()
        try:
            self.complete_chat("连接测试：请只回复 OK。")
        except ProviderError as exc:
            latency_ms = max(1, int((time.perf_counter() - started) * 1000))
            return ConnectionTestResult.from_provider_error(
                exc, latency_ms=latency_ms
            )
        except Exception as exc:
            latency_ms = max(1, int((time.perf_counter() - started) * 1000))
            return ConnectionTestResult(
                success=False,
                status="FAILED",
                latency_ms=latency_ms,
                error_code="PROVIDER_CONNECTION_ERROR",
                error_message=f"模型供应商连接失败：{exc}",
                provider_name=self.provider_display_name,
                provider_type=self.provider_type,
                model_name=self.model_name,
                endpoint=self.last_endpoint,
                timeout_ms=self.timeout_ms,
            )
        return ConnectionTestResult(
            success=True,
            status="SUCCESS",
            latency_ms=max(1, int((time.perf_counter() - started) * 1000)),
            provider_name=self.provider_display_name,
            provider_type=self.provider_type,
            model_name=self.model_name,
            endpoint=self.last_endpoint,
            timeout_ms=self.timeout_ms,
        )


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
                "MISSING_PROVIDER_CONFIG",
                "模型供应商未配置 base_url",
                **self._provider_error_context(),
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
        timeout_phase: str | None = None,
    ) -> dict:
        last_error: ProviderError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                self.last_endpoint = url
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.request(
                        method, url, headers=headers, json=json_body
                    )
                if response.status_code in self._RETRYABLE_STATUS:
                    last_error = self._status_error(
                        response, url=url, timeout_phase=timeout_phase
                    )
                    if attempt < self.max_retries:
                        self._sleep_backoff(attempt)
                        continue
                    raise last_error
                if response.status_code >= 400:
                    raise self._status_error(
                        response, url=url, timeout_phase=timeout_phase
                    )
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                is_timeout = isinstance(exc, httpx.TimeoutException)
                is_inference_timeout = (
                    is_timeout
                    and timeout_phase == "inference"
                    and isinstance(exc, httpx.ReadTimeout)
                )
                if is_timeout:
                    code = (
                        "PROVIDER_INFERENCE_TIMEOUT"
                        if is_inference_timeout
                        else "PROVIDER_CONNECTION_TIMEOUT"
                    )
                    phase = "read" if is_inference_timeout else "connect"
                else:
                    code = "PROVIDER_CONNECTION_ERROR"
                    phase = None
                last_error = ProviderError(
                    code,
                    (
                        "模型供应商连接失败："
                        if code == "PROVIDER_CONNECTION_TIMEOUT"
                        else "模型推理响应失败："
                    )
                    + str(exc),
                    retryable=True,
                    **self._provider_error_context(
                        endpoint=url, timeout_phase=phase
                    ),
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
        timeout_phase: str | None = None,
    ) -> Iterator[str]:
        try:
            self.last_endpoint = url
            with httpx.Client(timeout=self.timeout_seconds) as client:
                with client.stream(
                    "POST", url, headers=headers, json=json_body
                ) as response:
                    if response.status_code >= 400:
                        response.read()
                        raise self._status_error(
                            response, url=url, timeout_phase=timeout_phase
                        )
                    for line in response.iter_lines():
                        if line:
                            yield line
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            is_connect_timeout = isinstance(
                exc,
                (httpx.ConnectTimeout, httpx.PoolTimeout, httpx.WriteTimeout),
            )
            is_timeout = isinstance(exc, httpx.TimeoutException)
            is_inference_timeout = (
                is_timeout
                and timeout_phase == "inference"
                and isinstance(exc, httpx.ReadTimeout)
            )
            if is_timeout:
                code = (
                    "PROVIDER_INFERENCE_TIMEOUT"
                    if is_inference_timeout
                    else "PROVIDER_CONNECTION_TIMEOUT"
                )
                phase = "read" if is_inference_timeout else "connect"
            else:
                code = "PROVIDER_CONNECTION_ERROR"
                phase = None
            raise ProviderError(
                code,
                (
                    "模型供应商流式连接失败："
                    if code == "PROVIDER_CONNECTION_TIMEOUT"
                    else "模型推理流式响应失败："
                )
                + str(exc),
                retryable=True,
                **self._provider_error_context(
                    endpoint=url,
                    timeout_phase=phase,
                ),
            ) from exc

    def _status_error(
        self,
        response: httpx.Response,
        *,
        url: str | None = None,
        timeout_phase: str | None = None,
    ) -> ProviderError:
        retryable = response.status_code in self._RETRYABLE_STATUS
        code = "PROVIDER_SERVER_ERROR" if response.status_code >= 500 else "PROVIDER_REQUEST_ERROR"
        if response.status_code in (401, 403):
            code = "PROVIDER_UNAUTHORIZED"
        elif response.status_code == 429:
            code = "PROVIDER_RATE_LIMITED"
        message = self._extract_error_message(response)
        return ProviderError(
            code,
            message,
            retryable=retryable,
            status_code=response.status_code,
            **self._provider_error_context(endpoint=url),
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
                "MISSING_PROVIDER_CONFIG",
                "模型供应商未配置 model 名称",
                **self._provider_error_context(),
            )
        return self.model_name


class MockProvider(BaseProvider):
    """Deterministic in-process provider used by tests and local dev.

    Selected by the registry when the configuration signals mock mode
    (``mock://`` base_url, explicit fixtures, or an empty base_url). It never
    performs network I/O so the test suite stays hermetic.
    """

    provider_name = "mock"
    provider_type = "MOCK"

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
