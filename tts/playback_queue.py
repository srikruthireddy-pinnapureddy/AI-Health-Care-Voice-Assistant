import asyncio
from dataclasses import dataclass
from typing import Optional


@dataclass
class PlaybackItem:
    stream_sid: str
    frames: list[str]


class PlaybackQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[PlaybackItem] = asyncio.Queue()

    async def put(self, item: PlaybackItem) -> None:
        await self._queue.put(item)

    async def get(self) -> PlaybackItem:
        return await self._queue.get()

    async def drain(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()
