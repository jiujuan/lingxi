from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from server.tests.test_auth_rbac import build_test_client  # noqa: E402
from server.tests.test_chat_sse import _seed_chat_data  # noqa: E402
from server.tests.test_knowledge_documents_api import login_employee  # noqa: E402


def percentile(values: list[float], percent: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * percent)))
    return round(ordered[index], 3)


def main() -> None:
    iterations = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    client, SessionLocal = build_test_client()
    _seed_chat_data(SessionLocal)
    headers = login_employee(client)
    session_id = client.post("/api/v1/chat/sessions", headers=headers, json={}).json()["id"]

    first_token_latencies: list[float] = []
    failures = 0
    for _index in range(iterations):
        started = perf_counter()
        response = client.post(
            f"/api/v1/chat/sessions/{session_id}/message-runs",
            headers=headers,
            json={"content": "退款需要谁审批？"},
        )
        elapsed_ms = (perf_counter() - started) * 1000
        if response.status_code != 200 or "event: delta" not in response.text:
            failures += 1
        first_token_latencies.append(elapsed_ms)

    result = {
        "scenario": "chat_first_token_baseline",
        "iterations": iterations,
        "dataset": {"documents": 3, "qaPairs": 3},
        "firstTokenLatencyMs": {
            "p50": percentile(first_token_latencies, 0.50),
            "p95": percentile(first_token_latencies, 0.95),
            "avg": round(statistics.mean(first_token_latencies), 3)
            if first_token_latencies
            else 0,
        },
        "failureRate": round(failures * 100 / iterations, 2) if iterations else 0,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

