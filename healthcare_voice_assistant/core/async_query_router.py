import asyncio
import logging
import os
import time
from typing import Any, Dict, Optional, Tuple

from .query_router import process_query
from ..metrics.metrics_collector import get_metrics_collector
from session import session_manager
from session.session_cleanup import cleanup_expired_sessions as cleanup_worker
from session.state_machine import resolve_state

logger = logging.getLogger("clinic_voice_assistant.async_query_router")

_ACTIVE_TTL_SECONDS = int(os.getenv("SESSION_TTL_ACTIVE_SECONDS", "1800"))
_POST_CALL_TTL_SECONDS = int(os.getenv("SESSION_TTL_POST_CALL_SECONDS", "300"))


async def cleanup_stale_sessions(max_age_seconds: Optional[int] = None) -> int:
    max_age = max_age_seconds or (_ACTIVE_TTL_SECONDS + _POST_CALL_TTL_SECONDS)
    return await cleanup_worker(max_age_seconds=max_age)


async def cleanup_expired_sessions(max_age_seconds: Optional[int] = None) -> int:
    return await cleanup_stale_sessions(max_age_seconds=max_age_seconds)
async def get_session_context(session_id: str) -> Dict[str, Any]:
    return await session_manager.get_context(session_id)


async def save_session_context(
    session_id: str,
    context: Dict[str, Any],
    ttl_seconds: Optional[int] = None,
    expected_version: Optional[int] = None,
) -> bool:
    ttl = ttl_seconds if ttl_seconds is not None else _ACTIVE_TTL_SECONDS
    return await session_manager.save_context(
        session_id,
        context,
        ttl_seconds=ttl,
        expected_version=expected_version,
    )


async def set_session_ttl(session_id: str, ttl_seconds: int) -> None:
    await session_manager.set_ttl(session_id, ttl_seconds)


async def refresh_session_ttl(session_id: str, ttl_seconds: Optional[int] = None) -> None:
    await session_manager.refresh_ttl(session_id, ttl_seconds or _ACTIVE_TTL_SECONDS)


async def touch_session(session_id: str, ttl_seconds: Optional[int] = None) -> None:
    await session_manager.touch(session_id, ttl_seconds=ttl_seconds)


async def initialize_session(
    session_id: str,
    metadata: Optional[Dict[str, Any]] = None,
    ttl_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    return await session_manager.initialize(session_id, metadata=metadata, ttl_seconds=ttl_seconds)


async def process_query_async(
    query_text: str,
    session_id: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    collector = get_metrics_collector()
    lock_token = None
    start_time = time.perf_counter()

    for _ in range(3):
        lock_token = await session_manager.acquire_lock(session_id)
        if lock_token:
            break
        await asyncio.sleep(0.05)

    if not lock_token:
        logger.warning("Session lock contention | session_id=%s", session_id)
        context = await get_session_context(session_id)
        return {
            "intent": "fallback",
            "response": "We are still processing your last request. Please try again in a moment.",
            "actions": {"error": "lock_contention"},
        }, context

    try:
        context = await session_manager.get_context(session_id)
        session_manager.merge_metadata(context, metadata)
        context["last_activity_timestamp"] = int(time.time())
        current_version = int(context.get("session_version") or 0)
        previous_state = (context.get("conversation_state") or {}).get("state")

        result, updated_context = await asyncio.to_thread(process_query, query_text, context)

        updated_context["last_activity_timestamp"] = int(time.time())
        current_state = resolve_state(updated_context, result)
        updated_context["current_state"] = current_state

        history = list(updated_context.get("interaction_history") or [])
        history.append(
            {
                "timestamp": int(time.time()),
                "query": query_text,
                "intent": result.get("intent"),
                "response": result.get("response"),
                "actions": result.get("actions", {}),
            }
        )
        updated_context["interaction_history"] = history[-20:]

        saved = await save_session_context(
            session_id,
            updated_context,
            ttl_seconds=_ACTIVE_TTL_SECONDS,
            expected_version=current_version,
        )
        if not saved:
            logger.warning("Session version conflict | session_id=%s", session_id)
            await save_session_context(session_id, updated_context, ttl_seconds=_ACTIVE_TTL_SECONDS)
        latency_ms = (time.perf_counter() - start_time) * 1000
        collector.record_latency("routing_latency_ms", latency_ms)

        if previous_state != current_state and current_state:
            collector.record_transition(
                call_sid=updated_context.get("call_sid", session_id),
                from_state=previous_state or "unknown",
                to_state=current_state,
                latency_ms=latency_ms,
            )

        if result.get("intent") == "appointment_booking":
            actions = result.get("actions", {})
            if actions.get("booked") is True:
                collector.record_booking_completed(updated_context.get("call_sid", session_id))
            if actions.get("reason") == "slot_unavailable":
                collector.record_failed_booking(updated_context.get("call_sid", session_id))

        return result, updated_context
    finally:
        if lock_token:
            await session_manager.release_lock(session_id, lock_token)
