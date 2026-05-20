import logging
import threading

import torch
from faster_whisper import WhisperModel

logger = logging.getLogger("clinic_voice_assistant.whisper_engine")

_MODEL = None
_MODEL_LOCK = threading.Lock()


def _load_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL

    with _MODEL_LOCK:
        if _MODEL is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            compute_type = "float16" if device == "cuda" else "int8"
            logger.info("Loading Faster-Whisper model | device=%s compute_type=%s", device, compute_type)
            _MODEL = WhisperModel("small", device=device, compute_type=compute_type)
    return _MODEL


def transcribe_audio(audio_path):
    model = _load_model()
    segments, info = model.transcribe(
        audio_path,
        task="transcribe",
        language=None,
        beam_size=5,
        vad_filter=True,
    )

    text = " ".join(segment.text.strip() for segment in segments if segment.text).strip()
    language = info.language if info and info.language else "en"
    return {"text": text, "language": language}
