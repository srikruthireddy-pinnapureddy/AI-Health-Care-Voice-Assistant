import logging
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional

from healthcare_voice_assistant.metrics.latency_tracker import LatencyTracker
from healthcare_voice_assistant.speech.vad_engine import RealtimeVAD, RealtimeVADConfig
from healthcare_voice_assistant.speech.whisper_streaming import (
    StreamingWhisperConfig,
    WhisperStreaming,
)
from healthcare_voice_assistant.speech.transcription_worker import TranscriptionResult

logger = logging.getLogger("voice_gateway.realtime_pipeline")

TranscriptHandler = Callable[[TranscriptionResult, str], Awaitable[None]]


@dataclass(frozen=True)
class PipelineConfig:
    sample_rate_hz: int
    vad_threshold: float
    vad_silence_ms: int
    vad_min_speech_ms: int
    vad_max_chunk_ms: int
    stt_chunk_duration_s: float
    stt_min_chunk_duration_s: float
    stt_max_chunk_duration_s: float
    stt_language_hint: Optional[str] = None


class RealtimeSpeechPipeline:
    def __init__(
        self,
        call_sid: str,
        config: PipelineConfig,
        on_transcript: Optional[TranscriptHandler] = None,
    ) -> None:
        self._call_sid = call_sid
        self._config = config
        self._vad = RealtimeVAD(
            RealtimeVADConfig(
                sample_rate_hz=config.sample_rate_hz,
                silence_duration_ms=config.vad_silence_ms,
                min_speech_duration_ms=config.vad_min_speech_ms,
                max_chunk_duration_ms=config.vad_max_chunk_ms,
                threshold=config.vad_threshold,
            )
        )
        self._stt = WhisperStreaming(
            StreamingWhisperConfig(
                sample_rate_hz=config.sample_rate_hz,
                chunk_duration_s=config.stt_chunk_duration_s,
                min_chunk_duration_s=config.stt_min_chunk_duration_s,
                max_chunk_duration_s=config.stt_max_chunk_duration_s,
                language_hint=config.stt_language_hint,
            )
        )
        self._on_transcript = on_transcript

    def set_on_transcript(self, handler: Optional[TranscriptHandler]) -> None:
        self._on_transcript = handler

    async def start(self) -> None:
        await self._stt.start()

    async def stop(self) -> None:
        await self._stt.stop()

    async def reset(self) -> None:
        await self._vad.reset()
        await self._stt.reset()

    async def process_audio(self, pcm_bytes: bytes) -> bool:
        segments = await self._vad.process_audio(pcm_bytes)
        if not segments:
            return False

        for segment in segments:
            with LatencyTracker("stt_latency_ms", call_sid=self._call_sid):
                result = await self._stt.transcribe_chunk(segment.audio)
                if result is None:
                    result = await self._stt.flush()

            if result and result.text:
                if self._on_transcript:
                    await self._on_transcript(result, self._call_sid)
                else:
                    logger.info(
                        "Transcript ready",
                        extra={
                            "call_sid": self._call_sid,
                            "language": result.language,
                            "confidence": result.confidence,
                        },
                    )
        return True
