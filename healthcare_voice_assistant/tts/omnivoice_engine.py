import logging
import os
import threading
import uuid

import soundfile as sf
import torch

try:
    from omnivoice import OmniVoice
except Exception:
    OmniVoice = None

logger = logging.getLogger("clinic_voice_assistant.omnivoice_engine")

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
            logger.info("Loading OmniVoice model | device=%s", device)
            _MODEL = OmniVoice(device=device)
    return _MODEL


def generate_speech(text, output_dir=None, speaker=None):
    if not text:
        raise ValueError("Text is required for speech synthesis")

    output_dir = output_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated_audio")
    os.makedirs(output_dir, exist_ok=True)

    model = _load_model()
    voice_name = speaker or os.getenv("OMNIVOICE_SPEAKER", "receptionist")

    audio, sample_rate = model.tts(text, speaker=voice_name)
    file_name = f"reply_{uuid.uuid4().hex}.wav"
    output_path = os.path.join(output_dir, file_name)
    sf.write(output_path, audio, sample_rate)
    return output_path
