import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from .streaming_tts import StreamingTTS, StreamingTTSConfig

logger = logging.getLogger("voice_gateway.tts_worker_pool")


@dataclass
class TTSJob:
    text: str
    future: asyncio.Future


class TTSWorkerPool:
    def __init__(
        self,
        config: Optional[StreamingTTSConfig] = None,
        workers: int = 2,
        max_queue: int = 20,
    ) -> None:
        self._config = config or StreamingTTSConfig()
        self._workers = workers
        self._queue: asyncio.Queue[TTSJob] = asyncio.Queue(maxsize=max_queue)
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for _ in range(self._workers):
            self._tasks.append(asyncio.create_task(self._worker_loop()))

    async def stop(self) -> None:
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks = []

    async def submit(self, text: str) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        if self._queue.full():
            raise RuntimeError("TTS queue is full")
        await self._queue.put(TTSJob(text=text, future=future))
        return future

    async def _worker_loop(self) -> None:
        tts = StreamingTTS(self._config)
        while self._running:
            job = await self._queue.get()
            try:
                ulaw = await asyncio.to_thread(tts.synthesize_ulaw, job.text)
                if not job.future.done():
                    job.future.set_result(ulaw)
            except Exception as exc:
                logger.exception("TTS failed")
                if not job.future.done():
                    job.future.set_exception(exc)
