from dataclasses import dataclass


def _seconds(value: int | float | None, fallback_ms: int) -> float:
    try:
        milliseconds = float(value) if value is not None else float(fallback_ms)
    except (TypeError, ValueError):
        milliseconds = float(fallback_ms)
    return max(0.1, milliseconds / 1000)


@dataclass(frozen=True)
class ProviderTimeouts:
    connect_seconds: float
    write_seconds: float
    read_idle_seconds: float
    pool_seconds: float
    overall_seconds: float

    @classmethod
    def from_config(
        cls,
        *,
        legacy_timeout_ms: int | None,
        connect_timeout_ms: int | None,
        write_timeout_ms: int | None,
        read_idle_timeout_ms: int | None,
        overall_timeout_ms: int | None,
    ) -> "ProviderTimeouts":
        legacy = legacy_timeout_ms or 30000
        return cls(
            connect_seconds=_seconds(
                connect_timeout_ms, min(int(legacy), 10000)
            ),
            write_seconds=_seconds(write_timeout_ms, int(legacy)),
            read_idle_seconds=_seconds(read_idle_timeout_ms, int(legacy)),
            pool_seconds=_seconds(connect_timeout_ms, min(int(legacy), 10000)),
            overall_seconds=_seconds(overall_timeout_ms, int(legacy)),
        )
