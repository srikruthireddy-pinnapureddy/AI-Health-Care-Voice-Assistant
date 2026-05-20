import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    app_name: str = os.getenv("VOICE_GATEWAY_APP_NAME", "voice-gateway")
    log_level: str = os.getenv("VOICE_GATEWAY_LOG_LEVEL", "INFO")
    host: str = os.getenv("VOICE_GATEWAY_HOST", "0.0.0.0")
    port: int = int(os.getenv("VOICE_GATEWAY_PORT", "8001"))
    redis_url: str = os.getenv("VOICE_GATEWAY_REDIS_URL", "redis://localhost:6379/0")
    twilio_ws_url: str = os.getenv("VOICE_GATEWAY_TWILIO_WS_URL", "wss://example.com/media-stream")
    debug_audio_dir: str = os.getenv("VOICE_GATEWAY_DEBUG_AUDIO_DIR", "tmp_audio")
    debug_audio_max_chunks: int = int(os.getenv("VOICE_GATEWAY_DEBUG_AUDIO_MAX_CHUNKS", "5000"))
    audio_sample_rate_hz: int = int(os.getenv("VOICE_GATEWAY_SAMPLE_RATE_HZ", "8000"))
    audio_sample_width_bytes: int = int(os.getenv("VOICE_GATEWAY_SAMPLE_WIDTH_BYTES", "2"))
    audio_buffer_max_seconds: int = int(os.getenv("VOICE_GATEWAY_BUFFER_MAX_SECONDS", "30"))
    audio_chunk_duration_s: float = float(os.getenv("VOICE_GATEWAY_CHUNK_DURATION_S", "2.5"))
    audio_max_chunk_duration_s: float = float(os.getenv("VOICE_GATEWAY_MAX_CHUNK_DURATION_S", "4.0"))
    audio_rolling_buffer_seconds: int = int(os.getenv("VOICE_GATEWAY_ROLLING_BUFFER_SECONDS", "30"))
    vad_threshold: float = float(os.getenv("VOICE_GATEWAY_VAD_THRESHOLD", "0.5"))
    vad_silence_ms: int = int(os.getenv("VOICE_GATEWAY_VAD_SILENCE_MS", "600"))
    vad_min_speech_ms: int = int(os.getenv("VOICE_GATEWAY_VAD_MIN_SPEECH_MS", "200"))
    vad_max_chunk_ms: int = int(os.getenv("VOICE_GATEWAY_VAD_MAX_CHUNK_MS", "10000"))
    stt_chunk_duration_s: float = float(os.getenv("VOICE_GATEWAY_STT_CHUNK_DURATION_S", "3.0"))
    stt_min_chunk_duration_s: float = float(os.getenv("VOICE_GATEWAY_STT_MIN_CHUNK_DURATION_S", "2.0"))
    stt_max_chunk_duration_s: float = float(os.getenv("VOICE_GATEWAY_STT_MAX_CHUNK_DURATION_S", "4.0"))
    stt_language_hint: str = os.getenv("VOICE_GATEWAY_STT_LANGUAGE_HINT", "")
    tts_target_sample_rate_hz: int = int(os.getenv("VOICE_GATEWAY_TTS_SAMPLE_RATE_HZ", "8000"))
    tts_frame_duration_ms: int = int(os.getenv("VOICE_GATEWAY_TTS_FRAME_MS", "20"))
    tts_speaker: str = os.getenv("VOICE_GATEWAY_TTS_SPEAKER", "receptionist")
    tts_workers: int = int(os.getenv("VOICE_GATEWAY_TTS_WORKERS", "2"))
    tts_queue_max: int = int(os.getenv("VOICE_GATEWAY_TTS_QUEUE_MAX", "20"))

    @property
    def audio_buffer_max_bytes(self) -> int:
        return (
            self.audio_sample_rate_hz
            * self.audio_sample_width_bytes
            * self.audio_buffer_max_seconds
        )


settings = Settings()
