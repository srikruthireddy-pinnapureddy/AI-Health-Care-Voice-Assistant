import asyncio
import base64
import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from config import settings
from dependency_container import get_session_coordinator, get_tts_pool
from healthcare_voice_assistant.core.async_query_router import (
    initialize_session,
    process_query_async,
    set_session_ttl,
    touch_session,
)
from healthcare_voice_assistant.metrics.latency_tracker import LatencyTracker
from healthcare_voice_assistant.metrics.metrics_collector import get_metrics_collector
from healthcare_voice_assistant.core.translation_service import (
    LANG_EN,
    SUPPORTED_LANGUAGES,
    translate_from_english,
    translate_to_english,
)
from realtime_pipeline import RealtimeSpeechPipeline
from healthcare_voice_assistant.speech.transcription_worker import TranscriptionResult
from speech.audio_converter import ResampleState, resample_pcm16, ulaw_to_pcm16
from tts.playback_manager import PlaybackManager
from tts.streaming_tts import StreamingTTSConfig
from interruption.interruption_manager import InterruptionManager
from interruption.playback_canceller import PlaybackCanceller

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/media-stream")
async def media_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    collector = get_metrics_collector()
    collector.record_websocket_open()
    call_sid: str | None = None
    chunk_index = 0
    debug_dir = Path(settings.debug_audio_dir)
    debug_dir.mkdir(parents=True, exist_ok=True)
    websocket_id = None
    coordinator = get_session_coordinator()
    tts_pool = get_tts_pool()
    await tts_pool.start()
    resample_state = ResampleState()
    orchestrator = None
    pipeline: RealtimeSpeechPipeline | None = None
    stream_sid: str | None = None
    tts_config = StreamingTTSConfig(
        target_sample_rate_hz=settings.tts_target_sample_rate_hz,
        frame_duration_ms=settings.tts_frame_duration_ms,
        speaker=settings.tts_speaker,
    )
    playback_manager = PlaybackManager(
        websocket,
        frame_duration_ms=settings.tts_frame_duration_ms,
        tts_config=tts_config,
    )
    interruption = InterruptionManager(PlaybackCanceller(playback_manager))

    if websocket.client:
        websocket_id = f"{websocket.client.host}:{websocket.client.port}"

    try:
        while True:
            message = await websocket.receive_text()
            payload: dict[str, Any] = json.loads(message)
            event = payload.get("event")

            if event == "connected":
                logger.info("Media stream connected")

            elif event == "start":
                start = payload.get("start", {})
                received_sid = start.get("callSid")
                stream_sid = start.get("streamSid")
                language = start.get("language", "en")

                if received_sid:
                    call_sid = received_sid
                    pipeline = await coordinator.get_or_create_pipeline(
                        call_sid,
                        on_transcript=_on_transcript_factory(
                            websocket_id,
                            tts_pool,
                            playback_manager,
                            lambda: stream_sid,
                        ),
                    )
                    await pipeline.start()
                    orchestrator = await coordinator.get_or_create(
                        call_sid,
                        on_chunk=_on_chunk_factory(pipeline, interruption),
                    )
                    await coordinator.reset(call_sid)
                    await initialize_session(
                        session_id=call_sid,
                        metadata={
                            "call_sid": call_sid,
                            "websocket_id": websocket_id,
                            "language": language,
                            "current_state": "connected",
                        },
                    )
                    logger.info("Session initialized", extra={"call_sid": call_sid})
                    await touch_session(call_sid)
                else:
                    logger.warning("Start event missing callSid")

            elif event == "stop":
                if call_sid:
                    await initialize_session(
                        session_id=call_sid,
                        metadata={"current_state": "stopped"},
                    )
                    await set_session_ttl(call_sid, 300)
                logger.info("Media stream stopped", extra={"call_sid": call_sid})

            elif event == "media":
                media = payload.get("media", {})
                payload_b64 = media.get("payload")
                if not payload_b64:
                    logger.debug("Media event missing payload", extra={"call_sid": call_sid})
                    continue

                try:
                    raw = base64.b64decode(payload_b64)
                except ValueError:
                    logger.warning("Invalid base64 payload", extra={"call_sid": call_sid})
                    continue

                pcm = ulaw_to_pcm16(raw, settings.audio_sample_width_bytes)
                if settings.audio_sample_rate_hz != 8000:
                    pcm, resample_state = resample_pcm16(
                        pcm,
                        from_rate_hz=8000,
                        to_rate_hz=settings.audio_sample_rate_hz,
                        state=resample_state,
                    )
                if orchestrator:
                    await orchestrator.ingest_audio(pcm)
                if call_sid:
                    await touch_session(call_sid)
                    collector.record_throughput(call_sid, len(pcm))

                if chunk_index < settings.debug_audio_max_chunks:
                    if call_sid:
                        filename = f"{call_sid}_{chunk_index:08d}.pcm"
                    else:
                        filename = f"unknown_{chunk_index:08d}.pcm"
                    await asyncio.to_thread((debug_dir / filename).write_bytes, pcm)
                chunk_index += 1

            elif event == "transcript":
                transcript = payload.get("text", "")
                if not transcript or not call_sid:
                    continue
                with LatencyTracker("websocket_routing_latency_ms", call_sid=call_sid):
                    result, _ = await process_query_async(
                        query_text=transcript,
                        session_id=call_sid,
                        metadata={"call_sid": call_sid, "websocket_id": websocket_id},
                    )
                logger.info(
                    "Transcript processed",
                    extra={"call_sid": call_sid, "intent": result.get("intent")},
                )

            else:
                logger.debug("Unhandled event", extra={"event": event})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected", extra={"call_sid": call_sid})
    except json.JSONDecodeError:
        logger.warning("Invalid JSON payload", extra={"call_sid": call_sid})
    finally:
        collector.record_websocket_close(call_sid)
        if call_sid:
            await coordinator.remove(call_sid)
            await initialize_session(
                session_id=call_sid,
                metadata={"current_state": "disconnected"},
            )
            await set_session_ttl(call_sid, 300)


def _on_chunk_factory(pipeline: RealtimeSpeechPipeline, interruption: InterruptionManager):
    async def _on_chunk(audio: bytes, call_sid: str, duration_ms: int) -> None:
        logger.debug(
            "Audio chunk ready",
            extra={"call_sid": call_sid, "duration_ms": duration_ms, "bytes": len(audio)},
        )
        speech_detected = await pipeline.process_audio(audio)
        if speech_detected:
            await interruption.notify_speech(call_sid, duration_ms)

    return _on_chunk


def _on_transcript_factory(
    websocket_id: str | None,
    tts_pool,
    playback_manager: PlaybackManager,
    stream_sid_provider,
):
    async def _on_transcript(result: TranscriptionResult, call_sid: str) -> None:
        await touch_session(call_sid)
        language = result.language if result.language in SUPPORTED_LANGUAGES else LANG_EN
        query_english = translate_to_english(result.text, language)
        with LatencyTracker("websocket_routing_latency_ms", call_sid=call_sid):
            response, session_context = await process_query_async(
                query_text=query_english,
                session_id=call_sid,
                metadata={"call_sid": call_sid, "websocket_id": websocket_id, "language": language},
            )
        response_text = response.get("response", "")
        localized = translate_from_english(response_text, language)
        logger.info(
            "Transcript processed",
            extra={"call_sid": call_sid, "intent": response.get("intent")},
        )

        stream_sid = stream_sid_provider()
        if not stream_sid or not localized:
            return

        with LatencyTracker("tts_latency_ms", call_sid=call_sid):
            try:
                future = await tts_pool.submit(localized)
            except RuntimeError:
                collector.record_backpressure("tts_queue", call_sid=call_sid)
                return
            ulaw = await future

        await playback_manager.enqueue(call_sid, stream_sid, ulaw)

    return _on_transcript
