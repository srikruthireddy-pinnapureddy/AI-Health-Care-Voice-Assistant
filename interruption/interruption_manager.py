import logging
from typing import Optional

from .double_talk_handler import DoubleTalkHandler
from .playback_canceller import PlaybackCanceller
from .recovery_manager import RecoveryManager
from .speech_detector import SpeechDetection, SpeechDetector

logger = logging.getLogger("voice_gateway.interruption")


class InterruptionManager:
    def __init__(
        self,
        playback_canceller: PlaybackCanceller,
        detector: Optional[SpeechDetector] = None,
        double_talk_handler: Optional[DoubleTalkHandler] = None,
        recovery_manager: Optional[RecoveryManager] = None,
    ) -> None:
        self._playback_canceller = playback_canceller
        self._detector = detector or SpeechDetector()
        self._double_talk = double_talk_handler or DoubleTalkHandler()
        self._recovery = recovery_manager or RecoveryManager()

    async def notify_speech(self, call_sid: str, duration_ms: int, confidence: float = 0.7) -> None:
        detection = SpeechDetection(duration_ms=duration_ms, confidence=confidence)
        if not self._detector.is_interrupt(detection):
            return
        if self._double_talk.should_cancel():
            logger.info("Interruption detected", extra={"call_sid": call_sid})
            await self._playback_canceller.cancel(call_sid)
            self._recovery.on_cancelled(call_sid)
