import asyncio
from dataclasses import dataclass
from typing import List, Tuple


@dataclass(frozen=True)
class ScheduledChunk:
    audio: bytes
    start_sample: int
    end_sample: int


class ChunkScheduler:
    def __init__(
        self,
        sample_rate_hz: int,
        sample_width_bytes: int,
        chunk_duration_s: float,
        max_chunk_duration_s: float,
    ) -> None:
        self._sample_rate_hz = sample_rate_hz
        self._sample_width_bytes = sample_width_bytes
        self._chunk_bytes = int(sample_rate_hz * sample_width_bytes * chunk_duration_s)
        self._max_buffer_bytes = int(sample_rate_hz * sample_width_bytes * max_chunk_duration_s)
        self._buffer = bytearray()
        self._processed_samples = 0
        self._lock = asyncio.Lock()

    async def add_audio(self, pcm_bytes: bytes) -> List[ScheduledChunk]:
        chunks: List[ScheduledChunk] = []
        async with self._lock:
            self._buffer.extend(pcm_bytes)
            if len(self._buffer) > self._max_buffer_bytes:
                excess = len(self._buffer) - self._max_buffer_bytes
                del self._buffer[:excess]
                self._processed_samples += excess // self._sample_width_bytes

            while len(self._buffer) >= self._chunk_bytes:
                chunk = bytes(self._buffer[: self._chunk_bytes])
                del self._buffer[: self._chunk_bytes]
                start = self._processed_samples
                end = start + (len(chunk) // self._sample_width_bytes)
                chunks.append(ScheduledChunk(audio=chunk, start_sample=start, end_sample=end))
                self._processed_samples = end
        return chunks

    async def reset(self) -> None:
        async with self._lock:
            self._buffer.clear()
            self._processed_samples = 0
