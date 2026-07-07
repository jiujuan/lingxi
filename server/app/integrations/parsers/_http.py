"""Shared HTTP plumbing for parser-service clients (MinerU, Docling).

The retryable/non-retryable classification here is a contract with the Celery
retry pipeline (``tasks/_common.py`` acts on ``TaskRun.error.retryable``), so
it lives in one place instead of being duplicated per client. Response
envelope interpretation stays in each client — that is where version drift is
absorbed.
"""

import json
import time

import httpx

from server.app.integrations.parsers.base import ParserError

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class RetryingHttpClient:
    #: label used in Chinese error messages ("MinerU" / "Docling")
    service_label = "解析"

    def __init__(
        self,
        base_url: str | None,
        api_key: str | None = None,
        *,
        timeout_ms: int = 30000,
        poll_interval_seconds: float = 3.0,
        max_wait_seconds: int = 600,
        max_retries: int = 2,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/") or None
        self.api_key = api_key
        self.timeout_seconds = max(1.0, timeout_ms / 1000)
        self.poll_interval_seconds = max(0.1, poll_interval_seconds)
        self.max_wait_seconds = max(1, max_wait_seconds)
        self.max_retries = max(0, max_retries)

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _headers(self) -> dict[str, str]:
        return {}

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        timeout_seconds: float,
        data: dict | None = None,
        files: dict | None = None,
        params: dict | None = None,
    ) -> dict:
        last_error: ParserError | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with httpx.Client(timeout=timeout_seconds) as client:
                    response = client.request(
                        method,
                        url,
                        headers=self._headers(),
                        data=data,
                        files=files,
                        params=params,
                    )
                if response.status_code in _RETRYABLE_STATUS:
                    last_error = ParserError(
                        "PARSER_UNAVAILABLE",
                        f"{self.service_label} 服务返回 HTTP {response.status_code}",
                        retryable=True,
                    )
                    if attempt < self.max_retries:
                        self._sleep_backoff(attempt)
                        continue
                    raise last_error
                if response.status_code >= 400:
                    raise ParserError(
                        "PARSER_REQUEST_ERROR",
                        f"{self.service_label} 服务拒绝请求 HTTP {response.status_code}",
                        retryable=False,
                    )
                try:
                    payload = response.json()
                except (ValueError, json.JSONDecodeError) as exc:
                    raise ParserError(
                        "PARSER_RESPONSE_INVALID",
                        f"{self.service_label} 返回非 JSON 响应",
                    ) from exc
                if not isinstance(payload, dict):
                    raise ParserError(
                        "PARSER_RESPONSE_INVALID",
                        f"{self.service_label} 返回了非预期的响应结构",
                    )
                return payload
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = ParserError(
                    "PARSER_UNAVAILABLE",
                    f"{self.service_label} 服务连接失败：{exc}",
                    retryable=True,
                )
                if attempt < self.max_retries:
                    self._sleep_backoff(attempt)
                    continue
                raise last_error from exc
        raise last_error or ParserError(
            "PARSER_UNAVAILABLE", f"{self.service_label} 服务不可用", retryable=True
        )

    @staticmethod
    def _sleep_backoff(attempt: int) -> None:
        time.sleep(min(8.0, 0.5 * (2**attempt)))
