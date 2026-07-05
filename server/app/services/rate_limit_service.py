from collections import defaultdict, deque
from time import time


class RateLimitExceeded(Exception):
    pass


class RateLimitService:
    _hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit_per_minute: int) -> None:
        now = time()
        window_start = now - 60
        hits = self._hits[key]
        while hits and hits[0] < window_start:
            hits.popleft()
        if len(hits) >= limit_per_minute:
            raise RateLimitExceeded
        hits.append(now)
