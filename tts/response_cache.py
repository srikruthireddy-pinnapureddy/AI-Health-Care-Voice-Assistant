import time
from typing import Dict, Optional, Tuple


class ResponseCache:
    def __init__(self, ttl_seconds: int = 120) -> None:
        self._ttl = ttl_seconds
        self._store: Dict[str, Tuple[float, bytes]] = {}

    def get(self, key: str) -> Optional[bytes]:
        entry = self._store.get(key)
        if not entry:
            return None
        ts, value = entry
        if time.time() - ts > self._ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: bytes) -> None:
        self._store[key] = (time.time(), value)

    def clear(self) -> None:
        self._store.clear()
