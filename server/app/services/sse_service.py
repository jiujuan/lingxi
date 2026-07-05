from collections.abc import Iterator
import json
import queue
import threading

from server.app.core.config import settings

_DONE = object()


class SseService:
    @staticmethod
    def event(name: str, data: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    @staticmethod
    def comment(text: str = "heartbeat") -> str:
        # SSE comment frame: keeps the connection alive without emitting an event.
        return f": {text}\n\n"

    def stream_with_heartbeat(
        self, source: Iterator[str], interval: float | None = None
    ) -> Iterator[str]:
        """Relay ``source`` events, injecting a keep-alive comment during gaps.

        The source generator (retrieval + model streaming) can block for seconds
        with no output, which idle proxies may cut off. It runs in a background
        thread while this generator emits a heartbeat comment whenever no real
        event arrives within ``interval`` seconds. Only the worker thread touches
        the DB session; the main thread just relays, so there is no concurrent
        session access.
        """

        interval = interval if interval is not None else settings.sse_heartbeat_seconds
        events: queue.Queue = queue.Queue()
        state: dict = {}

        def worker() -> None:
            try:
                for item in source:
                    events.put(item)
            except BaseException as exc:  # noqa: BLE001 - re-raised on the main thread
                state["exc"] = exc
            finally:
                events.put(_DONE)

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        try:
            while True:
                try:
                    item = events.get(timeout=interval)
                except queue.Empty:
                    yield self.comment()
                    continue
                if item is _DONE:
                    break
                yield item
        finally:
            thread.join()
        if "exc" in state:
            raise state["exc"]
