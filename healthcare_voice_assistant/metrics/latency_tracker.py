import time
from typing import Optional

from .metrics_collector import get_metrics_collector


class LatencyTracker:
    def __init__(self, name: str, call_sid: Optional[str] = None) -> None:
        self._name = name
        self._call_sid = call_sid
        self._start = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb):
        latency_ms = (time.perf_counter() - self._start) * 1000
        get_metrics_collector().record_latency(self._name, latency_ms, call_sid=self._call_sid)
        return False
