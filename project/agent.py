import asyncio
import importlib
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional, Tuple

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from dotenv import load_dotenv  # type: ignore
from livekit.agents import (  # type: ignore
    Agent,
    AgentSession,
    AutoSubscribe,
    JobContext,
    RoomInputOptions,
    RoomOutputOptions,
    TurnHandlingOptions,
    WorkerOptions,
    cli,
)

LOG = logging.getLogger("clinic.livekit.agent")
STARTUP_LOG = logging.getLogger("clinic.livekit.startup")

_BACKEND_LOCK = asyncio.Lock()
_BACKEND: Optional["BackendAdapter"] = None
_BACKEND_ERROR: Optional[str] = None
_FALLBACK_CONTEXTS: Dict[str, Dict[str, Any]] = {}


def _is_debug_mode() -> bool:
    value = os.getenv("DEBUG_MODE", "false").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _setup_logging() -> None:
    if getattr(_setup_logging, "_configured", False):
        return

    debug_mode = _is_debug_mode()
    log_level = "DEBUG" if debug_mode else os.getenv("LOG_LEVEL", "INFO").upper()
    formatter = _JsonFormatter()

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(log_level)
    stream_handler.setFormatter(formatter)

    agent_handler = RotatingFileHandler(
        os.path.join(log_dir, "agent.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    agent_handler.setLevel(log_level)
    agent_handler.setFormatter(formatter)

    startup_handler = RotatingFileHandler(
        os.path.join(log_dir, "startup.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    startup_handler.setLevel(log_level)
    startup_handler.setFormatter(formatter)
    startup_handler.addFilter(_LoggerPrefixFilter("clinic.livekit.startup"))

    error_handler = RotatingFileHandler(
        os.path.join(log_dir, "errors.log"),
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)

    root_logger.addHandler(stream_handler)
    root_logger.addHandler(agent_handler)
    root_logger.addHandler(startup_handler)
    root_logger.addHandler(error_handler)

    logging.getLogger("livekit").setLevel(log_level)

    setattr(_setup_logging, "_configured", True)


class _LoggerPrefixFilter(logging.Filter):
    def __init__(self, prefix: str) -> None:
        super().__init__()
        self._prefix = prefix

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name.startswith(self._prefix)


class _JsonFormatter(logging.Formatter):
    _standard_attrs = {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "process",
        "processName",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        extras = {
            key: value
            for key, value in record.__dict__.items()
            if key not in self._standard_attrs and not key.startswith("_")
        }
        if extras:
            payload.update(extras)

        return json.dumps(payload, ensure_ascii=True)


def _get_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _resolve_session_id(ctx: JobContext) -> str:
    if getattr(ctx, "job", None) and getattr(ctx.job, "id", None):
        return ctx.job.id
    if getattr(ctx, "room", None) and getattr(ctx.room, "name", None):
        return ctx.room.name
    return f"session-{int(time.time())}"


def _default_fallback_context(session_id: str) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "call_sid": session_id,
        "current_state": "idle",
        "language": None,
        "interaction_history": [],
    }


@dataclass
class TranslationAdapter:
    lang_en: str = "en"
    supported_languages: Optional[set] = None
    language_confirmation: Optional[dict] = None

    def detect_language_choice(self, text: str) -> Optional[str]:
        return None

    def translate_to_english(self, text: str, source_lang: str) -> str:
        return text

    def translate_from_english(self, text: str, target_lang: str) -> str:
        return text


@dataclass
class BackendAdapter:
    get_session_context: Any
    initialize_session: Any
    process_query_async: Any
    set_session_ttl: Any
    touch_session: Any
    translation: TranslationAdapter


async def _import_module_timed(module_name: str) -> Tuple[Any, float]:
    def _do_import() -> Tuple[Any, float]:
        start = time.perf_counter()
        module = importlib.import_module(module_name)
        return module, (time.perf_counter() - start) * 1000

    return await asyncio.to_thread(_do_import)


async def _load_backend() -> None:
    global _BACKEND, _BACKEND_ERROR
    if _BACKEND or _BACKEND_ERROR:
        return

    async with _BACKEND_LOCK:
        if _BACKEND or _BACKEND_ERROR:
            return

        STARTUP_LOG.info("loading_backend")
        try:
            async_router, async_ms = await _import_module_timed(
                "healthcare_voice_assistant.core.async_query_router"
            )
            STARTUP_LOG.info(
                "backend_router_imported",
                extra={"duration_ms": round(async_ms, 2)},
            )

            translation_module, translation_ms = await _import_module_timed(
                "healthcare_voice_assistant.core.translation_service"
            )
            STARTUP_LOG.info(
                "backend_translation_imported",
                extra={"duration_ms": round(translation_ms, 2)},
            )

            translation = TranslationAdapter(
                lang_en=getattr(translation_module, "LANG_EN", "en"),
                supported_languages=getattr(
                    translation_module, "SUPPORTED_LANGUAGES", {"en"}
                ),
                language_confirmation=getattr(
                    translation_module, "LANGUAGE_CONFIRMATION", {}
                ),
            )
            translation.detect_language_choice = getattr(
                translation_module, "detect_language_choice"
            )
            translation.translate_to_english = getattr(
                translation_module, "translate_to_english"
            )
            translation.translate_from_english = getattr(
                translation_module, "translate_from_english"
            )

            _BACKEND = BackendAdapter(
                get_session_context=async_router.get_session_context,
                initialize_session=async_router.initialize_session,
                process_query_async=async_router.process_query_async,
                set_session_ttl=async_router.set_session_ttl,
                touch_session=async_router.touch_session,
                translation=translation,
            )
            STARTUP_LOG.info("backend_loaded")
        except Exception as exc:
            _BACKEND_ERROR = repr(exc)
            STARTUP_LOG.error("backend_load_failed", extra={"error": _BACKEND_ERROR})
            LOG.exception("backend_load_failed")
            if _is_debug_mode():
                traceback.print_exc()


async def _get_backend() -> Optional[BackendAdapter]:
    if _BACKEND is None and _BACKEND_ERROR is None:
        await _load_backend()
    return _BACKEND


async def _validate_redis() -> None:
    STARTUP_LOG.info("validating_redis")
    try:
        module, duration_ms = await _import_module_timed("session.redis_store")
        STARTUP_LOG.info(
            "redis_store_imported",
            extra={"duration_ms": round(duration_ms, 2)},
        )
        client = await module.get_redis()
        ping_start = time.perf_counter()
        await client.ping()
        ping_ms = (time.perf_counter() - ping_start) * 1000
        STARTUP_LOG.info("redis_ready", extra={"latency_ms": round(ping_ms, 2)})
    except Exception:
        LOG.exception("redis_validation_failed")
        traceback.print_exc()
        raise RuntimeError("Redis connectivity check failed")


async def _resolve_language(user_text: str, session_id: str) -> Tuple[str, Optional[str]]:
    backend = await _get_backend()
    if backend is None:
        return "en", None

    context = await backend.get_session_context(session_id)
    current = context.get("language")
    if backend.translation.supported_languages and current in backend.translation.supported_languages:
        return current, None

    detected = backend.translation.detect_language_choice(user_text)
    if backend.translation.supported_languages and detected in backend.translation.supported_languages:
        await backend.initialize_session(session_id, metadata={"language": detected})
        confirmation = (backend.translation.language_confirmation or {}).get(
            detected,
            (backend.translation.language_confirmation or {}).get(
                backend.translation.lang_en, ""
            ),
        )
        return detected, confirmation or None

    if current is None:
        await backend.initialize_session(
            session_id, metadata={"language": backend.translation.lang_en}
        )
    return backend.translation.lang_en, None


async def _safe_get_session_context(session_id: str) -> Dict[str, Any]:
    backend = await _get_backend()
    if backend is None:
        return _FALLBACK_CONTEXTS.get(session_id, _default_fallback_context(session_id))
    return await backend.get_session_context(session_id)


async def _safe_initialize_session(session_id: str, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    backend = await _get_backend()
    if backend is None:
        context = _FALLBACK_CONTEXTS.get(session_id, _default_fallback_context(session_id))
        if metadata:
            context.update({k: v for k, v in metadata.items() if v is not None})
        _FALLBACK_CONTEXTS[session_id] = context
        return context
    return await backend.initialize_session(session_id, metadata=metadata)


async def _safe_touch_session(session_id: str) -> None:
    backend = await _get_backend()
    if backend is None:
        context = _FALLBACK_CONTEXTS.get(session_id, _default_fallback_context(session_id))
        context["last_activity_timestamp"] = int(time.time())
        _FALLBACK_CONTEXTS[session_id] = context
        return
    await backend.touch_session(session_id)


async def _safe_set_session_ttl(session_id: str, ttl_seconds: int) -> None:
    backend = await _get_backend()
    if backend is None:
        return
    await backend.set_session_ttl(session_id, ttl_seconds)


async def _safe_process_query_async(
    query_text: str,
    session_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    backend = await _get_backend()
    if backend is None:
        return (
            {"response": "System is currently in maintenance mode."},
            _FALLBACK_CONTEXTS.get(session_id, _default_fallback_context(session_id)),
        )

    try:
        return await backend.process_query_async(
            query_text=query_text,
            session_id=session_id,
            metadata=metadata,
        )
    except Exception:
        LOG.exception("backend_process_failed", extra={"session_id": session_id})
        traceback.print_exc()
        return (
            {"response": "Sorry, the booking system is temporarily unavailable."},
            await _safe_get_session_context(session_id),
        )


class ClinicReceptionist(Agent):
    def __init__(self) -> None:
        instructions = (
            "You are a multilingual healthcare receptionist. "
            "Speak in short, calm, and professional responses. "
            "Stay within healthcare-safe guidance. "
            "Do not provide medical diagnosis or treatment advice. "
            "If a caller reports urgent or life-threatening symptoms, "
            "instruct them to seek emergency care immediately."
        )
        super().__init__(
            instructions=instructions,
            allow_interruptions=True,
            turn_handling=TurnHandlingOptions(
                {
                    "endpointing": {"min_delay": 0.4, "max_delay": 3.0},
                    "interruption": {"enabled": True, "min_duration": 0.4},
                    "preemptive_generation": {"enabled": False},
                }
            ),
        )

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        session = self.session
        session_id = session.userdata.get("session_id")
        user_text = (getattr(new_message, "text_content", None) or "").strip()
        if not user_text:
            return

        start_time = time.perf_counter()
        await _safe_touch_session(session_id)
        language, response_override = await _resolve_language(user_text, session_id)

        if response_override:
            LOG.info(
                "language_confirmed",
                extra={"session_id": session_id, "language": language},
            )
            session.say(response_override, allow_interruptions=True)
            return

        backend = await _get_backend()
        if backend is None:
            session.say("System is currently in maintenance mode.", allow_interruptions=True)
            return

        query_english = backend.translation.translate_to_english(user_text, language)

        result, _ = await _safe_process_query_async(
            query_text=query_english,
            session_id=session_id,
            metadata={
                "call_sid": session_id,
                "language": language,
                "current_state": "active",
            },
        )
        response_text = result.get("response", "")
        localized = backend.translation.translate_from_english(response_text, language)
        session.say(localized, allow_interruptions=True)

        latency_ms = (time.perf_counter() - start_time) * 1000
        LOG.info(
            "turn_completed",
            extra={
                "session_id": session_id,
                "language": language,
                "intent": result.get("intent"),
                "latency_ms": round(latency_ms, 2),
                "user_text": user_text,
                "assistant_text": localized,
            },
        )


async def entrypoint(ctx: JobContext) -> None:
    env_path = Path(__file__).resolve().parent / ".env"
    print(f"Loading env from: {env_path}")
    load_dotenv(dotenv_path=env_path)
    print("LIVEKIT_URL =", os.getenv("LIVEKIT_URL"))
    print("LIVEKIT_API_KEY =", os.getenv("LIVEKIT_API_KEY"))
    _setup_logging()
    debug_mode = _is_debug_mode()

    STARTUP_LOG.info("starting_worker", extra={"debug": debug_mode})

    try:
        _get_env("LIVEKIT_URL")
        _get_env("LIVEKIT_API_KEY")
        _get_env("LIVEKIT_API_SECRET")
        STARTUP_LOG.info("env_validated")

        await _validate_redis()

        await _load_backend()
        if _BACKEND_ERROR:
            STARTUP_LOG.error("backend_unavailable", extra={"error": _BACKEND_ERROR})

        session_id = _resolve_session_id(ctx)
        ctx.log_context_fields = {"session_id": session_id}

        STARTUP_LOG.info(
            "connecting_to_room",
            extra={"session_id": session_id, "worker_id": ctx.worker_id},
        )

        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
        STARTUP_LOG.info("room_connected", extra={"session_id": session_id})

        participant = await ctx.wait_for_participant()
        LOG.info(
            "participant_joined",
            extra={"session_id": session_id, "participant": participant.identity},
        )

        await _safe_initialize_session(
            session_id=session_id,
            metadata={
                "call_sid": session_id,
                "current_state": "connected",
                "livekit_room": ctx.room.name,
                "participant_identity": participant.identity,
            },
        )

        stt_model = os.getenv("LIVEKIT_STT_MODEL", "cartesia/ink-whisper")
        tts_model = os.getenv("LIVEKIT_TTS_MODEL", "cartesia/sonic")
        STARTUP_LOG.info(
            "agent_session_config",
            extra={"stt_model": stt_model, "tts_model": tts_model},
        )

        session = AgentSession(
            stt=stt_model,
            tts=tts_model,
            turn_handling=TurnHandlingOptions(
                {
                    "endpointing": {"min_delay": 0.4, "max_delay": 3.0},
                    "interruption": {"enabled": True, "min_duration": 0.4},
                    "preemptive_generation": {"enabled": False},
                }
            ),
            userdata={"session_id": session_id},
        )

        try:
            session.on(
                "agent_state_changed",
                lambda ev: LOG.debug(
                    "agent_state_changed",
                    extra={"session_id": session_id, "state": getattr(ev, "new_state", None)},
                ),
            )
            session.on(
                "user_state_changed",
                lambda ev: LOG.debug(
                    "user_state_changed",
                    extra={"session_id": session_id, "state": getattr(ev, "new_state", None)},
                ),
            )
            session.on(
                "speech_created",
                lambda ev: LOG.debug(
                    "speech_created",
                    extra={"session_id": session_id, "source": getattr(ev, "source", None)},
                ),
            )
        except Exception:
            LOG.exception("session_event_hook_failed", extra={"session_id": session_id})

        async def _shutdown_callback(reason: str = "") -> None:
            LOG.info(
                "job_shutdown",
                extra={"session_id": session_id, "reason": reason},
            )
            await _safe_initialize_session(
                session_id=session_id,
                metadata={"current_state": "disconnected"},
            )
            await _safe_set_session_ttl(session_id, 300)

        ctx.add_shutdown_callback(_shutdown_callback)

        STARTUP_LOG.info("starting_agent_session", extra={"session_id": session_id})
        await session.start(
            ClinicReceptionist(),
            room=ctx.room,
            room_input_options=RoomInputOptions(participant_identity=participant.identity),
            room_output_options=RoomOutputOptions(transcription_enabled=True),
        )
        STARTUP_LOG.info("agent_ready", extra={"session_id": session_id})
    except Exception:
        LOG.exception("entrypoint_failed")
        traceback.print_exc()
        raise


if __name__ == "__main__":
    try:
        cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
    except Exception:
        LOG.exception("worker_startup_failed")
        traceback.print_exc()
        raise
