from dataclasses import dataclass


@dataclass(frozen=True)
class SpeechDetection:
    duration_ms: int
    confidence: float


class SpeechDetector:
    def is_interrupt(self, detection: SpeechDetection) -> bool:
        return detection.duration_ms >= 200 and detection.confidence >= 0.5
