"""Minimal, dependency-free Prometheus metrics.

The module deliberately keeps labels to a small, closed vocabulary. Request,
document, user, question, and content identifiers belong in structured logs,
not metric labels.
"""

import threading
from collections.abc import Mapping, Sequence

_LATENCY_BUCKETS = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
_TOKEN_BUCKETS = (16.0, 32.0, 64.0, 128.0, 256.0, 512.0, 1024.0, 2048.0)

_lock = threading.Lock()
_request_totals: dict[tuple[str, str, int], int] = {}
_latency_sum: dict[tuple[str, str], float] = {}
_latency_count: dict[tuple[str, str], int] = {}
_latency_buckets: dict[tuple[str, str, float], int] = {}

_counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_histogram_sum: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
_histogram_count: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
_histogram_buckets: dict[
    tuple[str, tuple[tuple[str, str], ...], float], int
] = {}


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


def observe_chunking(
    *,
    duration_seconds: float,
    token_counts_by_block_type: Mapping[str, Sequence[int]],
    tiny_count: int = 0,
    oversized_count: int = 0,
    merge_count: int = 0,
    split_count: int = 0,
) -> None:
    """Record adaptive chunking health without any document-derived labels."""

    with _lock:
        _observe_histogram("chunking_duration_seconds", duration_seconds, {}, _LATENCY_BUCKETS)
        for block_type, token_counts in token_counts_by_block_type.items():
            for token_count in token_counts:
                _observe_histogram(
                    "chunk_tokens",
                    float(token_count),
                    {"block_type": str(block_type)},
                    _TOKEN_BUCKETS,
                )
        _increment("chunk_tiny_total", {}, tiny_count)
        _increment("chunk_oversized_total", {}, oversized_count)
        _increment("chunk_merge_total", {}, merge_count)
        _increment("chunk_split_total", {}, split_count)


def observe_qa_provenance_validation_failure(reason: str) -> None:
    with _lock:
        _increment(
            "qa_provenance_validation_failure_total",
            {"reason": reason},
        )


def observe_qa_chunk_coverage_ratio(ratio: float) -> None:
    with _lock:
        _set_gauge("qa_chunk_coverage_ratio", {}, ratio)


def observe_embedding_targets(target_type: str, status: str, count: int) -> None:
    with _lock:
        _increment(
            "embedding_targets_total",
            {"type": target_type, "status": status},
            count,
        )


def observe_retrieval(
    *,
    candidate_counts: Mapping[str, int],
    channel_hit_ratios: Mapping[str, float],
    dedup_ratio: float,
    hydration_tokens: int,
    latency_by_stage_seconds: Mapping[str, float],
    degraded_reason: str | None = None,
) -> None:
    """Record bounded retrieval channel/stage metrics."""

    with _lock:
        for channel, count in candidate_counts.items():
            _increment("retrieval_candidates_total", {"channel": channel}, count)
        for channel, ratio in channel_hit_ratios.items():
            _set_gauge("retrieval_channel_hit_ratio", {"channel": channel}, ratio)
        _set_gauge("retrieval_dedup_ratio", {}, dedup_ratio)
        _observe_histogram(
            "retrieval_hydration_tokens",
            float(hydration_tokens),
            {},
            _TOKEN_BUCKETS,
        )
        for stage, duration_seconds in latency_by_stage_seconds.items():
            _observe_histogram(
                "retrieval_latency_seconds",
                duration_seconds,
                {"stage": stage},
                _LATENCY_BUCKETS,
            )
        if degraded_reason:
            _increment("retrieval_degraded_total", {"reason": degraded_reason})


def reset() -> None:
    with _lock:
        _request_totals.clear()
        _latency_sum.clear()
        _latency_count.clear()
        _latency_buckets.clear()
        _counters.clear()
        _gauges.clear()
        _histogram_sum.clear()
        _histogram_count.clear()
        _histogram_buckets.clear()


def render_prometheus() -> str:
    lines: list[str] = []
    with _lock:
        _render_http_metrics(lines)
        _render_counter(
            lines, "chunk_tiny_total", "Tiny chunks emitted by adaptive chunking."
        )
        _render_counter(
            lines, "chunk_oversized_total", "Oversized chunks detected by adaptive chunking."
        )
        _render_counter(
            lines, "chunk_merge_total", "Adaptive chunk merge operations."
        )
        _render_counter(
            lines, "chunk_split_total", "Adaptive chunk split operations."
        )
        _render_counter(
            lines,
            "qa_provenance_validation_failure_total",
            "QA provenance validation failures by stable reason.",
        )
        _render_counter(
            lines,
            "embedding_targets_total",
            "Embedding targets processed by stable type and status.",
        )
        _render_counter(
            lines,
            "retrieval_candidates_total",
            "Candidates returned by retrieval channel.",
        )
        _render_counter(
            lines,
            "retrieval_degraded_total",
            "Retrieval degradation events by stable reason.",
        )
        _render_gauge(
            lines, "qa_chunk_coverage_ratio", "Ratio of source chunks represented by QA."
        )
        _render_gauge(
            lines,
            "retrieval_channel_hit_ratio",
            "Fraction of retrieval channel requests with candidates.",
        )
        _render_gauge(
            lines, "retrieval_dedup_ratio", "Fraction of fused evidence removed by deduplication."
        )
        _render_histogram(
            lines,
            "chunking_duration_seconds",
            "Adaptive chunking duration.",
            _LATENCY_BUCKETS,
        )
        _render_histogram(
            lines, "chunk_tokens", "Adaptive chunk token distribution.", _TOKEN_BUCKETS
        )
        _render_histogram(
            lines,
            "retrieval_hydration_tokens",
            "Tokens selected for retrieval context hydration.",
            _TOKEN_BUCKETS,
        )
        _render_histogram(
            lines,
            "retrieval_latency_seconds",
            "Retrieval latency by bounded pipeline stage.",
            _LATENCY_BUCKETS,
        )
    return "\n".join(lines) + "\n"


def _render_http_metrics(lines: list[str]) -> None:
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


def _increment(name: str, labels: Mapping[str, object], value: int | float = 1) -> None:
    key = (name, _label_key(labels))
    _counters[key] = _counters.get(key, 0.0) + float(value)


def _set_gauge(name: str, labels: Mapping[str, object], value: float) -> None:
    _gauges[(name, _label_key(labels))] = float(value)


def _observe_histogram(
    name: str,
    value: float,
    labels: Mapping[str, object],
    buckets: Sequence[float],
) -> None:
    key = (name, _label_key(labels))
    _histogram_sum[key] = _histogram_sum.get(key, 0.0) + value
    _histogram_count[key] = _histogram_count.get(key, 0) + 1
    for bucket in buckets:
        if value <= bucket:
            bucket_key = (name, key[1], bucket)
            _histogram_buckets[bucket_key] = _histogram_buckets.get(bucket_key, 0) + 1


def _render_counter(lines: list[str], name: str, help_text: str) -> None:
    lines.append(f"# HELP lingxi_{name} {help_text}")
    lines.append(f"# TYPE lingxi_{name} counter")
    for (metric_name, labels), value in sorted(_counters.items()):
        if metric_name == name:
            lines.append(f"lingxi_{name}{_format_labels(labels)} {_format_number(value)}")


def _render_gauge(lines: list[str], name: str, help_text: str) -> None:
    lines.append(f"# HELP lingxi_{name} {help_text}")
    lines.append(f"# TYPE lingxi_{name} gauge")
    for (metric_name, labels), value in sorted(_gauges.items()):
        if metric_name == name:
            lines.append(f"lingxi_{name}{_format_labels(labels)} {_format_number(value)}")


def _render_histogram(
    lines: list[str],
    name: str,
    help_text: str,
    buckets: Sequence[float],
) -> None:
    lines.append(f"# HELP lingxi_{name} {help_text}")
    lines.append(f"# TYPE lingxi_{name} histogram")
    for (metric_name, labels), total in sorted(_histogram_count.items()):
        if metric_name != name:
            continue
        for bucket in buckets:
            count = _histogram_buckets.get((name, labels, bucket), 0)
            lines.append(
                f"lingxi_{name}_bucket"
                f"{_format_labels((*labels, ('le', str(bucket))))} {count}"
            )
        lines.append(
            f"lingxi_{name}_bucket"
            f"{_format_labels((*labels, ('le', '+Inf')))} {total}"
        )
        lines.append(
            f"lingxi_{name}_sum{_format_labels(labels)} "
            f"{_format_number(_histogram_sum[(metric_name, labels)])}"
        )
        lines.append(f"lingxi_{name}_count{_format_labels(labels)} {total}")


def _label_key(labels: Mapping[str, object]) -> tuple[tuple[str, str], ...]:
    return tuple(sorted((str(name), str(value)) for name, value in labels.items()))


def _format_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    return "{" + ",".join(
        f'{name}="{_escape(value)}"' for name, value in sorted(labels)
    ) + "}"


def _format_number(value: float) -> str:
    return str(int(value)) if value.is_integer() else f"{value:.6f}"


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')
