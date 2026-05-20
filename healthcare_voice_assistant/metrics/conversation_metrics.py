from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class StateTransitionEvent:
    call_sid: str
    from_state: str
    to_state: str
    timestamp: str
    latency_ms: Optional[float] = None
