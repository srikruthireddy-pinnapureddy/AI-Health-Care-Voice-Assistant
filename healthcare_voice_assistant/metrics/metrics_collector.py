import logging
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from .conversation_metrics import StateTransitionEvent

logger = logging.getLogger("clinic_voice_assistant.metrics")


class MetricsCollector:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: Dict[str, int] = defaultdict(int)
        self._latencies: Dict[str, Deque[float]] = defaultdict(lambda: deque(maxlen=200))
        self._transition_events: Deque[StateTransitionEvent] = deque(maxlen=1000)
        self._call_traces: Dict[str, Deque[StateTransitionEvent]] = defaultdict(lambda: deque(maxlen=200))
        self._throughput_bytes: Dict[str, int] = defaultdict(int)

    def record_transition(
        self,
        call_sid: str,
        from_state: str,
        to_state: str,
        latency_ms: Optional[float] = None,
    ) -> None:
        event = StateTransitionEvent(
            call_sid=call_sid,
            from_state=from_state,
            to_state=to_state,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            latency_ms=latency_ms,
        )
        with self._lock:
            self._transition_events.append(event)
            self._call_traces[call_sid].append(event)
        logger.info(
            "state_transition",
            extra={
                "call_sid": call_sid,
                "from_state": from_state,
                "to_state": to_state,
                "latency_ms": latency_ms,
            },
        )

    def record_latency(self, name: str, value_ms: float, call_sid: Optional[str] = None) -> None:
        with self._lock:
            self._latencies[name].append(value_ms)
            self._counters[f"{name}_count"] += 1
        logger.debug("latency", extra={"metric": name, "value_ms": value_ms, "call_sid": call_sid})

    def record_stt_latency(self, value_ms: float, call_sid: Optional[str] = None) -> None:
        self.record_latency("stt_latency_ms", value_ms, call_sid=call_sid)

    def record_tts_latency(self, value_ms: float, call_sid: Optional[str] = None) -> None:
        self.record_latency("tts_latency_ms", value_ms, call_sid=call_sid)

    def record_interruption(self, call_sid: str) -> None:
        with self._lock:
            self._counters["interruptions"] += 1
            self._counters[f"interruptions:{call_sid}"] += 1

    def record_failed_booking(self, call_sid: str) -> None:
        with self._lock:
            self._counters["failed_bookings"] += 1
            self._counters[f"failed_bookings:{call_sid}"] += 1

    def record_booking_completed(self, call_sid: str) -> None:
        with self._lock:
            self._counters["booking_completed"] += 1
            self._counters[f"booking_completed:{call_sid}"] += 1

    def record_silence_timeout(self, call_sid: str) -> None:
        with self._lock:
            self._counters["silence_timeouts"] += 1
            self._counters[f"silence_timeouts:{call_sid}"] += 1

    def record_throughput(self, call_sid: str, byte_count: int) -> None:
        with self._lock:
            self._throughput_bytes[call_sid] += byte_count

    def record_websocket_open(self, call_sid: Optional[str] = None) -> None:
        with self._lock:
            self._counters["websocket_open"] += 1
            if call_sid:
                self._counters[f"websocket_open:{call_sid}"] += 1

    def record_websocket_close(self, call_sid: Optional[str] = None) -> None:
        with self._lock:
            self._counters["websocket_close"] += 1
            if call_sid:
                self._counters[f"websocket_close:{call_sid}"] += 1

    def record_backpressure(self, label: str, call_sid: Optional[str] = None) -> None:
        with self._lock:
            self._counters[f"backpressure:{label}"] += 1
            if call_sid:
                self._counters[f"backpressure:{label}:{call_sid}"] += 1

    def get_snapshot(self) -> dict:
        with self._lock:
            latency_summary = {
                name: {
                    "avg_ms": sum(values) / len(values) if values else 0.0,
                    "p95_ms": sorted(values)[int(0.95 * (len(values) - 1))] if values else 0.0,
                    "count": len(values),
                }
                for name, values in self._latencies.items()
            }
            return {
                "counters": dict(self._counters),
                "latencies": latency_summary,
                "throughput_bytes": dict(self._throughput_bytes),
                "recent_transitions": [event.__dict__ for event in list(self._transition_events)],
            }

    def get_call_trace(self, call_sid: str) -> list:
        with self._lock:
            return [event.__dict__ for event in self._call_traces.get(call_sid, [])]


_COLLECTOR: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    global _COLLECTOR
    if _COLLECTOR is None:
        _COLLECTOR = MetricsCollector()
    return _COLLECTOR
