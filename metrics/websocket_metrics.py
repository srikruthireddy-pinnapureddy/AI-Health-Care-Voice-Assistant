from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class WebsocketEvent:
    call_sid: Optional[str]
    event: str
    timestamp: str
