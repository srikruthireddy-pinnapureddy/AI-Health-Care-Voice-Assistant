import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import torch
import soundfile as sf

logger = logging.getLogger("clinic_voice_assistant.vad_engine")

_VAD_MODEL = None
_VAD_UTILS = None


def _load_vad():
    global _VAD_MODEL, _VAD_UTILS
    if _VAD_MODEL is None:
        logger.info("Loading Silero VAD model")
        _VAD_MODEL, _VAD_UTILS = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
            onnx=False,
        )
    return _VAD_MODEL, _VAD_UTILS


@dataclass(frozen=True)
class RealtimeVADConfig:
    sample_rate_hz: int = 16000
    frame_duration_ms: int = 20
    silence_duration_ms: int = 600
    min_speech_duration_ms: int = 200
    max_chunk_duration_ms: int = 10000
    threshold: float = 0.5
    debug_audio_dir: Optional[str] = None


@dataclass
class SpeechSegment:
    audio: bytes
    sample_rate_hz: int
    start_sample: int
    end_sample: int

    @property
    def duration_ms(self) -> int:
        return int((self.end_sample - self.start_sample) * 1000 / self.sample_rate_hz)


class RealtimeVAD:
    def __init__(self, config: Optional[RealtimeVADConfig] = None) -> None:
        self._config = config or RealtimeVADConfig()
        self._model, self._utils = _load_vad()
        _, _, _, vad_iterator = self._utils
        try:
            self._vad = vad_iterator(
                self._model,
                threshold=self._config.threshold,
                sampling_rate=self._config.sample_rate_hz,
                min_silence_duration_ms=self._config.silence_duration_ms,
            )
        except TypeError:
            self._vad = vad_iterator(
                self._model,
                threshold=self._config.threshold,
                sampling_rate=self._config.sample_rate_hz,
            )

        from .audio_utils import frame_size_bytes, pcm16_bytes_to_float32
        from .stream_buffer import RollingAudioBuffer

        self._frame_bytes = frame_size_bytes(
            self._config.sample_rate_hz,
            self._config.frame_duration_ms,
        )
        self._frame_samples = int(
            self._config.sample_rate_hz * self._config.frame_duration_ms / 1000
        )
        self._pcm_to_float = pcm16_bytes_to_float32
        self._rolling_buffer = RollingAudioBuffer(self._max_chunk_bytes())
        self._input_buffer = bytearray()
        self._speech_buffer = bytearray()
        self._speech_start_sample = 0
        self._processed_samples = 0
        self._speech_started = False
        self._lock = asyncio.Lock()
        self._debug_dir = self._prepare_debug_dir()

    async def process_audio(self, pcm_bytes: bytes) -> List[SpeechSegment]:
        segments: List[SpeechSegment] = []
        async with self._lock:
            self._input_buffer.extend(pcm_bytes)
            while len(self._input_buffer) >= self._frame_bytes:
                frame = bytes(self._input_buffer[: self._frame_bytes])
                del self._input_buffer[: self._frame_bytes]
                await self._rolling_buffer.append(frame)

                float_frame = self._pcm_to_float(frame)
                tensor = torch.from_numpy(float_frame)
                event = self._vad(tensor)
                self._processed_samples += self._frame_samples

                if event and event.get("start") is not None:
                    self._speech_started = True
                    self._speech_start_sample = int(event["start"])
                    logger.debug("Speech start", extra={"start": self._speech_start_sample})

                if self._speech_started:
                    self._speech_buffer.extend(frame)

                if event and event.get("end") is not None:
                    end_sample = int(event["end"])
                    segment = self._finalize_segment(end_sample)
                    if segment:
                        segments.append(segment)
                    self._speech_started = False

                if self._speech_started and len(self._speech_buffer) >= self._max_chunk_bytes():
                    end_sample = self._processed_samples
                    segment = self._finalize_segment(end_sample)
                    if segment:
                        segments.append(segment)
                    self._speech_started = True
                    self._speech_start_sample = self._processed_samples

        return segments

    async def flush(self) -> List[SpeechSegment]:
        async with self._lock:
            if not self._speech_buffer:
                return []
            end_sample = self._processed_samples
            segment = self._finalize_segment(end_sample)
            self._speech_started = False
            return [segment] if segment else []

    async def get_recent_audio(self) -> bytes:
        return await self._rolling_buffer.snapshot()

    async def reset(self) -> None:
        async with self._lock:
            self._input_buffer.clear()
            self._speech_buffer.clear()
            self._speech_started = False
            self._processed_samples = 0
            self._speech_start_sample = 0
            await self._rolling_buffer.clear()
            self._vad.reset_states()

    def _finalize_segment(self, end_sample: int) -> Optional[SpeechSegment]:
        segment = SpeechSegment(
            audio=bytes(self._speech_buffer),
            sample_rate_hz=self._config.sample_rate_hz,
            start_sample=self._speech_start_sample,
            end_sample=end_sample,
        )
        self._speech_buffer.clear()

        if segment.duration_ms < self._config.min_speech_duration_ms:
            logger.debug("Discarded short segment", extra={"duration_ms": segment.duration_ms})
            return None

        self._write_debug_segment(segment)
        return segment

    def _max_chunk_bytes(self) -> int:
        samples = int(self._config.sample_rate_hz * self._config.max_chunk_duration_ms / 1000)
        return samples * 2

    def _prepare_debug_dir(self) -> Optional[Path]:
        if not self._config.debug_audio_dir:
            return None
        path = Path(self._config.debug_audio_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_debug_segment(self, segment: SpeechSegment) -> None:
        if not self._debug_dir:
            return
        filename = f"segment_{segment.start_sample}_{segment.end_sample}.pcm"
        path = self._debug_dir / filename
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, path.write_bytes, segment.audio)
        except RuntimeError:
            path.write_bytes(segment.audio)


def detect_speech(audio_path, threshold=0.5) -> bool:
    model, utils = _load_vad()
    get_speech_timestamps, _, read_audio, _ = utils

    wav = read_audio(audio_path, sampling_rate=16000)
    timestamps = get_speech_timestamps(wav, model, threshold=threshold)
    return bool(timestamps)


def trim_silence(audio_path: str, output_path: str, threshold=0.5) -> Tuple[str, bool]:
    model, utils = _load_vad()
    get_speech_timestamps, _, read_audio, _ = utils

    wav = read_audio(audio_path, sampling_rate=16000)
    timestamps = get_speech_timestamps(wav, model, threshold=threshold)
    if not timestamps:
        return audio_path, False

    start = timestamps[0]["start"]
    end = timestamps[-1]["end"]
    trimmed = wav[start:end]

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    sf.write(output_path, trimmed, 16000)
    return output_path, True
