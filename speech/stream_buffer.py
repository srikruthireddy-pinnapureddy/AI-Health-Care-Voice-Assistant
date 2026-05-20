import asyncio
from collections import deque
from typing import Deque


class RollingAudioBuffer:
    def __init__(self, max_bytes: int) -> None:
        self._max_bytes = max_bytes
        self._chunks: Deque[bytes] = deque()
        self._size = 0
        self._lock = asyncio.Lock()

    async def append(self, data: bytes) -> None:
        async with self._lock:
            self._chunks.append(data)
            self._size += len(data)
            while self._size > self._max_bytes and self._chunks:
                removed = self._chunks.popleft()
                self._size -= len(removed)

    async def snapshot(self) -> bytes:
        async with self._lock:
            return b"".join(self._chunks)

    async def clear(self) -> None:
        async with self._lock:
            self._chunks.clear()
            self._size = 0
