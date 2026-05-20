import logging
import os

import ffmpeg
import numpy as np

logger = logging.getLogger("clinic_voice_assistant.audio_utils")


def normalize_audio(input_path, output_path):
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input audio not found: {input_path}")

    try:
        (
            ffmpeg
            .input(input_path)
            .output(output_path, format="wav", acodec="pcm_s16le", ac=1, ar="16000")
            .overwrite_output()
            .run(quiet=True)
        )
        return output_path
    except ffmpeg.Error as exc:
        logger.exception("FFmpeg normalization failed")
        raise RuntimeError("Audio normalization failed") from exc


def frame_size_bytes(
    sample_rate_hz: int,
    frame_duration_ms: int,
    sample_width_bytes: int = 2,
) -> int:
    samples_per_frame = int(sample_rate_hz * frame_duration_ms / 1000)
    return samples_per_frame * sample_width_bytes


def split_audio_frames(pcm_bytes: bytes, frame_bytes: int):
    for offset in range(0, len(pcm_bytes), frame_bytes):
        chunk = pcm_bytes[offset : offset + frame_bytes]
        if len(chunk) == frame_bytes:
            yield chunk


def pcm16_bytes_to_float32(pcm_bytes: bytes) -> np.ndarray:
    pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
    return pcm.astype(np.float32) / 32768.0
