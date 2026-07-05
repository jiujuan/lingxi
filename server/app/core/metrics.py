"""Minimal, dependency-free Prometheus metrics.

Tracks HTTP request counts and latency and renders the Prometheus text
exposition format at /metrics — no prometheus_client dependency, no scrape
collector required to be useful. Labels use the route *template*
(e.g. /api/v1/import-jobs/{job_id}) to keep cardinality bounded.
"""

import threading

_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_lock = threading.Lock()
_request_totals: dict[tuple[str, str, int], int] = {}
_latency_sum: dict[tuple[str, str], float] = {}
_latency_count: dict[tuple[str, str], int] = {}
_latency_buckets: dict[tuple[str, str, float], int] = {}


def observe_request(method: str, path: str, status: int, duration_seconds: float) -> None:
    with _lock:
        _request_totals[(method, path, status)] = (
            _request_totals.get((method, path, status), 0) + 1
        )
        route = (method, path)
        _latency_sum[route] = _latency_sum.get(route, 0.0) + duration_seconds
        _latency_count[route] = _latency_count.get(route, 0) + 1
        for bucket in _LATENCY_BUCKETS:
            if duration_seconds <= bucket:
                key = (method, path, bucket)
                _latency_buckets[key] = _latency_buckets.get(key, 0) + 1


def reset() -> None:
    with _lock:
        _request_totals.clear()
        _latency_sum.clear()
        _latency_count.clear()
        _latency_buckets.clear()


def render_prometheus() -> str:
    lines: list[str] = []
    with _lock:
        lines.append("# HELP lingxi_http_requests_total Total HTTP requests.")
        lines.append("# TYPE lingxi_http_requests_total counter")
        for (method, path, status), count in sorted(_request_totals.items()):
            lines.append(
                f'lingxi_http_requests_total{{method="{method}",'
                f'path="{_escape(path)}",status="{status}"}} {count}'
            )

        lines.append("# HELP lingxi_http_request_duration_seconds HTTP request latency.")
        lines.append("# TYPE lingxi_http_request_duration_seconds histogram")
        for route in sorted(_latency_count):
            method, path = route
            labels = f'method="{method}",path="{_escape(path)}"'
            cumulative = 0
            for bucket in _LATENCY_BUCKETS:
                cumulative = _latency_buckets.get((method, path, bucket), 0)
                lines.append(
                    f'lingxi_http_request_duration_seconds_bucket{{{labels},'
                    f'le="{bucket}"}} {cumulative}'
                )
            total = _latency_count[route]
            lines.append(
                f'lingxi_http_request_duration_seconds_bucket{{{labels},le="+Inf"}} {total}'
            )
            lines.append(
                f"lingxi_http_request_duration_seconds_sum{{{labels}}} "
                f"{_latency_sum[route]:.6f}"
            )
            lines.append(
                f"lingxi_http_request_duration_seconds_count{{{labels}}} {total}"
            )
    return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
