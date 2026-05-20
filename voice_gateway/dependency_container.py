from config import settings
from realtime_orchestrator import OrchestratorConfig
from realtime_pipeline import PipelineConfig
from session_coordinator import SessionCoordinator
from tts.streaming_tts import StreamingTTSConfig
from tts.tts_worker_pool import TTSWorkerPool


_session_coordinator: SessionCoordinator | None = None
_tts_pool: TTSWorkerPool | None = None


def get_session_coordinator() -> SessionCoordinator:
    global _session_coordinator
    if _session_coordinator is None:
        config = OrchestratorConfig(
            sample_rate_hz=settings.audio_sample_rate_hz,
            sample_width_bytes=settings.audio_sample_width_bytes,
            chunk_duration_s=settings.audio_chunk_duration_s,
            max_chunk_duration_s=settings.audio_max_chunk_duration_s,
            rolling_buffer_seconds=settings.audio_rolling_buffer_seconds,
        )
        pipeline_config = PipelineConfig(
            sample_rate_hz=settings.audio_sample_rate_hz,
            vad_threshold=settings.vad_threshold,
            vad_silence_ms=settings.vad_silence_ms,
            vad_min_speech_ms=settings.vad_min_speech_ms,
            vad_max_chunk_ms=settings.vad_max_chunk_ms,
            stt_chunk_duration_s=settings.stt_chunk_duration_s,
            stt_min_chunk_duration_s=settings.stt_min_chunk_duration_s,
            stt_max_chunk_duration_s=settings.stt_max_chunk_duration_s,
            stt_language_hint=(settings.stt_language_hint or None),
        )
        _session_coordinator = SessionCoordinator(config, pipeline_config)
    return _session_coordinator


def get_tts_pool() -> TTSWorkerPool:
    global _tts_pool
    if _tts_pool is None:
        tts_config = StreamingTTSConfig(
            target_sample_rate_hz=settings.tts_target_sample_rate_hz,
            frame_duration_ms=settings.tts_frame_duration_ms,
            speaker=settings.tts_speaker,
        )
        _tts_pool = TTSWorkerPool(
            tts_config,
            workers=settings.tts_workers,
            max_queue=settings.tts_queue_max,
        )
    return _tts_pool
