import audioop
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class ResampleState:
    state: Optional[bytes] = None


def ulaw_to_pcm16(ulaw_bytes: bytes, sample_width_bytes: int = 2) -> bytes:
    return audioop.ulaw2lin(ulaw_bytes, sample_width_bytes)


def resample_pcm16(
    pcm_bytes: bytes,
    from_rate_hz: int,
    to_rate_hz: int,
    state: Optional[ResampleState] = None,
) -> Tuple[bytes, ResampleState]:
    if from_rate_hz == to_rate_hz:
        return pcm_bytes, state or ResampleState()

    current_state = state or ResampleState()
    resampled, new_state = audioop.ratecv(
        pcm_bytes,
        2,
        1,
        from_rate_hz,
        to_rate_hz,
        current_state.state,
    )
    return resampled, ResampleState(new_state)
