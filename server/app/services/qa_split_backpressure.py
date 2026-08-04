"""Provider-scoped concurrency control for long-running QA batches."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import threading
import time
from typing import TypeVar

from server.app.core import metrics
from server.app.services._batching import run_ordered

T = TypeVar("T")
R = TypeVar("R")

BACKPRESSURE_RETRYABLE_CODES = frozenset(
    {
        "PROVIDER_RATE_LIMITED",
        "PROVIDER_SERVER_ERROR",
        "PROVIDER_INFERENCE_TIMEOUT",
        "PROVIDER_OVERALL_TIMEOUT",
    }
)


@dataclass
class BackpressureState:
    current_concurrency: int
    min_concurrency: int
    max_concurrency: int
    consecutive_successes: int = 0
    provider_type: str | None = None

    def __post_init__(self) -> None:
        self.min_concurrency = max(1, int(self.min_concurrency))
        self.max_concurrency = max(self.min_concurrency, int(self.max_concurrency))
        self.current_concurrency = min(
            self.max_concurrency,
            max(self.min_concurrency, int(self.current_concurrency)),
        )
        self._observe_concurrency()

    def _observe_concurrency(self) -> None:
        metrics.observe_qa_split_concurrency(
            provider_type=self.provider_type,
            concurrency=self.current_concurrency,
        )

    def on_retryable_failure(self, code: str) -> int:
        if code not in BACKPRESSURE_RETRYABLE_CODES:
            return self.current_concurrency
        self.current_concurrency = max(
            self.min_concurrency,
            self.current_concurrency // 2,
        )
        self.consecutive_successes = 0
        self._observe_concurrency()
        return self.current_concurrency

    def on_success(self) -> int:
        self.consecutive_successes += 1
        if self.consecutive_successes >= 3:
            self.current_concurrency = min(
                self.max_concurrency,
                self.current_concurrency + 1,
            )
            self.consecutive_successes = 0
            self._observe_concurrency()
        return self.current_concurrency


_state_lock = threading.Lock()
_states: dict[tuple[str, str], BackpressureState] = {}


def get_backpressure_state(
    provider_id: str,
    model_config_id: str,
    *,
    current_concurrency: int,
    min_concurrency: int,
    max_concurrency: int,
    provider_type: str | None = None,
) -> BackpressureState:
    """Return a state isolated to one provider/model pair."""

    key = (str(provider_id), str(model_config_id))
    with _state_lock:
        state = _states.get(key)
        if state is None:
            state = BackpressureState(
                current_concurrency=current_concurrency,
                min_concurrency=min_concurrency,
                max_concurrency=max_concurrency,
                provider_type=provider_type,
            )
            _states[key] = state
        else:
            if provider_type is not None:
                state.provider_type = provider_type
            state.min_concurrency = max(1, int(min_concurrency))
            state.max_concurrency = max(
                state.min_concurrency, int(max_concurrency)
            )
            state.current_concurrency = min(
                state.max_concurrency,
                max(state.min_concurrency, state.current_concurrency),
            )
            state._observe_concurrency()
        return state


def reset_backpressure_states() -> None:
    """Clear process-local state for tests and controlled worker reloads."""

    with _state_lock:
        _states.clear()


def _result_error_code(result: object) -> str | None:
    error = getattr(result, "error", None)
    code = getattr(error, "code", None) if error is not None else None
    return code if isinstance(code, str) else None


def _update_state(state: BackpressureState, result: object) -> None:
    code = _result_error_code(result)
    if code in BACKPRESSURE_RETRYABLE_CODES:
        state.on_retryable_failure(code)
        time.sleep(0.5)
    else:
        state.on_success()


def run_ordered_with_backpressure(
    items: Sequence[T],
    worker: Callable[[T], R],
    state: BackpressureState,
) -> list[R]:
    """Run bounded waves, adapting the next wave to provider pressure."""

    results: list[R] = []
    offset = 0
    while offset < len(items):
        width = min(
            max(1, state.current_concurrency),
            len(items) - offset,
        )
        wave = items[offset : offset + width]
        try:
            wave_results = run_ordered(wave, worker, width)
        except Exception as exc:
            code = getattr(exc, "code", None)
            if isinstance(code, str) and code in BACKPRESSURE_RETRYABLE_CODES:
                state.on_retryable_failure(code)
                time.sleep(0.5)
            raise
        for result in wave_results:
            _update_state(state, result)
        results.extend(wave_results)
        offset += width
    return results
