import asyncio
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from speech.chunk_scheduler import ChunkScheduler
from speech.stream_buffer import RollingAudioBuffer

logger = logging.getLogger("voice_gateway.realtime_orchestrator")

ChunkHandler = Callable[[bytes, str, int], Awaitable[None]]


@dataclass
class OrchestratorConfig:
    sample_rate_hz: int
    sample_width_bytes: int
    chunk_duration_s: float
    max_chunk_duration_s: float
    rolling_buffer_seconds: int


class RealtimeOrchestrator:
    def __init__(
        self,
        call_sid: str,
        config: OrchestratorConfig,
        on_chunk: Optional[ChunkHandler] = None,
    ) -> None:
        self._call_sid = call_sid
        self._config = config
        self._scheduler = ChunkScheduler(
            sample_rate_hz=config.sample_rate_hz,
            sample_width_bytes=config.sample_width_bytes,
            chunk_duration_s=config.chunk_duration_s,
            max_chunk_duration_s=config.max_chunk_duration_s,
        )
        max_bytes = int(
            config.sample_rate_hz
            * config.sample_width_bytes
            * config.rolling_buffer_seconds
        )
        self._rolling_buffer = RollingAudioBuffer(max_bytes)
        self._on_chunk = on_chunk
        self._lock = asyncio.Lock()

    def set_on_chunk(self, on_chunk: Optional[ChunkHandler]) -> None:
        self._on_chunk = on_chunk

    async def ingest_audio(self, pcm_bytes: bytes) -> None:
        async with self._lock:
            await self._rolling_buffer.append(pcm_bytes)
            scheduled = await self._scheduler.add_audio(pcm_bytes)

        for chunk in scheduled:
            duration_ms = int(
                (chunk.end_sample - chunk.start_sample)
                * 1000
                / self._config.sample_rate_hz
            )
            if self._on_chunk:
                await self._on_chunk(chunk.audio, self._call_sid, duration_ms)
            else:
                logger.debug(
                    "Chunk ready",
                    extra={
                        "call_sid": self._call_sid,
                        "duration_ms": duration_ms,
                        "bytes": len(chunk.audio),
                    },
                )

    async def recent_audio(self) -> bytes:
        return await self._rolling_buffer.snapshot()

    async def reset(self) -> None:
        await self._scheduler.reset()
        await self._rolling_buffer.clear()
