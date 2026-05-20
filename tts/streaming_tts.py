import audioop
import base64
import logging
from dataclasses import dataclass
from typing import Iterable, List, Optional

from .omnivoice_engine import synthesize

logger = logging.getLogger("voice_gateway.streaming_tts")


@dataclass(frozen=True)
class StreamingTTSConfig:
    target_sample_rate_hz: int = 8000
    frame_duration_ms: int = 20
    speaker: Optional[str] = None


class StreamingTTS:
    def __init__(self, config: Optional[StreamingTTSConfig] = None) -> None:
        self._config = config or StreamingTTSConfig()

    def synthesize_ulaw(self, text: str) -> bytes:
        pcm, sample_rate = synthesize(text, speaker=self._config.speaker)
        if sample_rate != self._config.target_sample_rate_hz:
            pcm, _ = audioop.ratecv(
                pcm,
                2,
                1,
                sample_rate,
                self._config.target_sample_rate_hz,
                None,
            )
        ulaw = audioop.lin2ulaw(pcm, 2)
        return ulaw

    def iter_frames(self, ulaw_bytes: bytes) -> Iterable[bytes]:
        frame_bytes = int(self._config.target_sample_rate_hz * self._config.frame_duration_ms / 1000)
        for offset in range(0, len(ulaw_bytes), frame_bytes):
            chunk = ulaw_bytes[offset : offset + frame_bytes]
            if len(chunk) == frame_bytes:
                yield chunk

    def encode_frames(self, ulaw_bytes: bytes) -> List[str]:
        return [base64.b64encode(frame).decode("ascii") for frame in self.iter_frames(ulaw_bytes)]
