import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from .audio_utils import pcm16_bytes_to_float32
from .transcription_worker import TranscriptionResult, TranscriptionWorker

logger = logging.getLogger("clinic_voice_assistant.whisper_streaming")


@dataclass(frozen=True)
class StreamingWhisperConfig:
    sample_rate_hz: int = 16000
    chunk_duration_s: float = 3.0
    min_chunk_duration_s: float = 2.0
    max_chunk_duration_s: float = 4.0
    language_hint: Optional[str] = None


class WhisperStreaming:
    def __init__(self, config: Optional[StreamingWhisperConfig] = None) -> None:
        self._config = config or StreamingWhisperConfig()
        self._worker = TranscriptionWorker()
        self._buffer = bytearray()
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        await self._worker.start()

    async def stop(self) -> None:
        await self._worker.stop()

    async def reset(self) -> None:
        async with self._lock:
            self._buffer.clear()

    async def transcribe_chunk(self, pcm_bytes: bytes) -> Optional[TranscriptionResult]:
        async with self._lock:
            self._buffer.extend(pcm_bytes)
            duration_s = len(self._buffer) / (self._config.sample_rate_hz * 2)

            if duration_s < self._config.min_chunk_duration_s:
                return None

            if duration_s > self._config.max_chunk_duration_s:
                logger.debug("Chunk exceeded max duration", extra={"duration_s": duration_s})

            chunk_size = int(self._config.chunk_duration_s * self._config.sample_rate_hz * 2)
            if len(self._buffer) < chunk_size:
                return None

            chunk = bytes(self._buffer[:chunk_size])
            del self._buffer[:chunk_size]

        audio = pcm16_bytes_to_float32(chunk)
        future = await self._worker.submit(
            audio=audio,
            sample_rate_hz=self._config.sample_rate_hz,
            language=self._config.language_hint,
        )
        result = await future
        return result

    async def flush(self) -> Optional[TranscriptionResult]:
        async with self._lock:
            if not self._buffer:
                return None
            chunk = bytes(self._buffer)
            self._buffer.clear()

        audio = pcm16_bytes_to_float32(chunk)
        future = await self._worker.submit(
            audio=audio,
            sample_rate_hz=self._config.sample_rate_hz,
            language=self._config.language_hint,
        )
        return await future
