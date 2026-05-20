import logging
import os
import threading
from typing import Tuple

import numpy as np
import torch

try:
    from omnivoice import OmniVoice
except Exception:
    OmniVoice = None

logger = logging.getLogger("voice_gateway.omnivoice_engine")

_MODEL = None
_MODEL_LOCK = threading.Lock()


def _load_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    if OmniVoice is None:
        raise RuntimeError("OmniVoice library not available. Install the omnivoice package.")

    with _MODEL_LOCK:
        if _MODEL is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            logger.info("Loading OmniVoice model", extra={"device": device})
            _MODEL = OmniVoice(device=device)
    return _MODEL


def synthesize(text: str, speaker: str | None = None) -> Tuple[bytes, int]:
    if not text:
        raise ValueError("Text is required for speech synthesis")

    model = _load_model()
    voice_name = speaker or os.getenv("OMNIVOICE_SPEAKER", "receptionist")

    audio, sample_rate = model.tts(text, speaker=voice_name)
    audio = np.asarray(audio, dtype=np.float32)
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767.0).astype(np.int16).tobytes()
    return pcm, int(sample_rate)
