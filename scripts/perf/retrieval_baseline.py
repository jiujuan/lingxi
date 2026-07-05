from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.tests.test_document_permissions import build_session  # noqa: E402
from server.tests.test_retrieval_service import (  # noqa: E402
    _employee_context,
    _seed_retrieval_dataset,
)


QUESTIONS = [
    "退款需要谁审批？",
    "已开票订单退款前要做什么？",
    "火星基地报销制度是什么？",
]


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percent)))
    return round(ordered[index], 3)


def main() -> None:
    iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    session, identity = build_session()
    from server.app.services.retrieval_service import RetrievalService

    _seed_retrieval_dataset(session, identity)
    context = _employee_context(identity)
    service = RetrievalService(session)
    latencies: list[float] = []
    failures = 0

    for index in range(iterations):
        question = QUESTIONS[index % len(QUESTIONS)]
        started = perf_counter()
        try:
            service.retrieve(context, question)
        except Exception:
            failures += 1
        latencies.append((perf_counter() - started) * 1000)

    result = {
        "scenario": "hybrid_retrieval_baseline",
        "iterations": iterations,
        "dataset": {"documents": 3, "qaPairs": 3},
        "latencyMs": {
            "p50": percentile(latencies, 0.50),
            "p95": percentile(latencies, 0.95),
            "avg": round(statistics.mean(latencies), 3) if latencies else 0,
        },
        "failureRate": round(failures * 100 / iterations, 2) if iterations else 0,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
