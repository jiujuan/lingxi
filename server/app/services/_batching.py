"""Ordered, concurrency-capped execution helper.

Used by the QA-split and embedding services to fan out network-bound model
calls across a bounded thread pool while keeping results in input order. Only
side-effect-free network calls run in the pool; the caller performs all DB
writes on the main thread afterwards, so the shared SQLAlchemy Session is never
touched concurrently.
"""

from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")


def run_ordered(
    items: Sequence[T], worker: Callable[[T], R], max_workers: int
) -> list[R]:
    """Apply ``worker`` to each item, returning results in input order.

    Runs sequentially when ``max_workers <= 1`` or there is at most one item;
    otherwise fans out over a bounded thread pool. Exceptions propagate to the
    caller (the first one encountered).
    """

    if not items:
        return []
    workers = max(1, int(max_workers))
    if workers == 1 or len(items) == 1:
        return [worker(item) for item in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as executor:
        return list(executor.map(worker, items))
