import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import numpy as np
import torch
from faster_whisper import WhisperModel

logger = logging.getLogger("clinic_voice_assistant.transcription_worker")

_MODEL: Optional[WhisperModel] = None
_MODEL_LOCK = asyncio.Lock()


@dataclass
class TranscriptionResult:
    text: str
    language: str
    confidence: float
    latency_ms: float


def _resolve_device() -> tuple[str, str]:
    if torch.cuda.is_available():
        return "cuda", "float16"
    return "cpu", "int8"


async def get_model() -> WhisperModel:
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    async with _MODEL_LOCK:
        if _MODEL is None:
            device, compute_type = _resolve_device()
            logger.info("Loading Faster-Whisper model", extra={"device": device, "compute": compute_type})
            _MODEL = WhisperModel("small", device=device, compute_type=compute_type)
    return _MODEL


def _confidence_from_segments(segments: Any) -> float:
    probs = [getattr(segment, "avg_logprob", None) for segment in segments]
    clean = [float(p) for p in probs if isinstance(p, (int, float))]
    if not clean:
        return 0.0
    return max(min(sum(clean) / len(clean), 1.0), -1.0)


async def transcribe_audio(
    audio: np.ndarray,
    sample_rate_hz: int,
    language: Optional[str] = None,
) -> TranscriptionResult:
    model = await get_model()
    started = time.perf_counter()

    segments, info = model.transcribe(
        audio,
        language=language,
        task="transcribe",
        beam_size=5,
        vad_filter=False,
        temperature=0.0,
        initial_prompt=None,
    )

    text = " ".join(segment.text.strip() for segment in segments if segment.text).strip()
    detected_language = info.language if info and info.language else (language or "en")
    confidence = _confidence_from_segments(segments)
    latency_ms = (time.perf_counter() - started) * 1000

    return TranscriptionResult(
        text=text,
        language=detected_language,
        confidence=confidence,
        latency_ms=latency_ms,
    )


class TranscriptionWorker:
    def __init__(self, batch_size: int = 4, batch_timeout_ms: int = 120) -> None:
        self._queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._batch_size = batch_size
        self._batch_timeout_ms = batch_timeout_ms
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task

    async def submit(
        self,
        audio: np.ndarray,
        sample_rate_hz: int,
        language: Optional[str] = None,
    ) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        await self._queue.put(
            {
                "audio": audio,
                "sample_rate_hz": sample_rate_hz,
                "language": language,
                "future": future,
            }
        )
        return future

    async def _run(self) -> None:
        await get_model()
        while self._running:
            batch = []
            start_time = time.perf_counter()

            while len(batch) < self._batch_size:
                timeout = self._batch_timeout_ms / 1000
                remaining = timeout - (time.perf_counter() - start_time)
                if remaining <= 0 and batch:
                    break

                try:
                    item = await asyncio.wait_for(self._queue.get(), timeout=max(remaining, 0.01))
                    batch.append(item)
                except asyncio.TimeoutError:
                    if batch:
                        break

            if not batch:
                continue

            for item in batch:
                future = item["future"]
                try:
                    result = await transcribe_audio(
                        item["audio"],
                        item["sample_rate_hz"],
                        language=item["language"],
                    )
                    if not future.done():
                        future.set_result(result)
                except Exception as exc:
                    logger.exception("Transcription failed")
                    if not future.done():
                        future.set_exception(exc)

