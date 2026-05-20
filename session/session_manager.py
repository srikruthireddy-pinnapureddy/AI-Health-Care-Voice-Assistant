import json
import time
from typing import Any, Dict, Optional

from . import redis_store
from .session_locks import acquire_session_lock, release_session_lock

_DEFAULT_TTL_SECONDS = 60 * 30


def session_key(session_id: str) -> str:
    return f"session:{session_id}"


def default_context(session_id: str) -> Dict[str, Any]:
    return {
        "session_id": session_id,
        "call_sid": session_id,
        "websocket_id": None,
        "current_state": "idle",
        "language": None,
        "pending_intent": None,
        "booking_context": {},
        "missing_fields": [],
        "conversation_state": {},
        "last_activity_timestamp": None,
        "interruption_state": {},
        "interaction_history": [],
        "last_assistant_response": None,
        "playback_state": {},
        "session_version": 0,
    }


def merge_metadata(context: Dict[str, Any], metadata: Optional[Dict[str, Any]]) -> None:
    if not metadata:
        return
    for key in (
        "call_sid",
        "websocket_id",
        "current_state",
        "pending_intent",
        "missing_fields",
        "language",
        "interruption_state",
        "interaction_history",
        "last_assistant_response",
        "playback_state",
    ):
        if key in metadata and metadata[key] is not None:
            context[key] = metadata[key]


async def get_context(session_id: str) -> Dict[str, Any]:
    raw = await redis_store.get_value(session_key(session_id))
    if not raw:
        return default_context(session_id)
    try:
        payload = json.loads(raw)
    except Exception:
        payload = {}
    defaults = default_context(session_id)
    defaults.update(payload)
    return defaults


async def save_context(
    session_id: str,
    context: Dict[str, Any],
    ttl_seconds: Optional[int] = None,
    expected_version: Optional[int] = None,
) -> bool:
    ttl = ttl_seconds or _DEFAULT_TTL_SECONDS
    next_version = int(context.get("session_version") or 0) + 1
    context["session_version"] = next_version
    value_json = json.dumps(context)

    if expected_version is None:
        await redis_store.set_value(session_key(session_id), value_json, ttl)
        return True

    return await redis_store.compare_and_set_json(
        session_key(session_id),
        value_json,
        ttl,
        expected_version,
    )


async def touch(session_id: str, ttl_seconds: Optional[int] = None) -> None:
    context = await get_context(session_id)
    context["last_activity_timestamp"] = int(time.time())
    await save_context(session_id, context, ttl_seconds=ttl_seconds)


async def initialize(
    session_id: str,
    metadata: Optional[Dict[str, Any]] = None,
    ttl_seconds: Optional[int] = None,
) -> Dict[str, Any]:
    context = await get_context(session_id)
    merge_metadata(context, metadata)
    context["last_activity_timestamp"] = int(time.time())
    await save_context(session_id, context, ttl_seconds=ttl_seconds)
    return context


async def set_ttl(session_id: str, ttl_seconds: int) -> None:
    await redis_store.expire(session_key(session_id), ttl_seconds)


async def refresh_ttl(session_id: str, ttl_seconds: Optional[int] = None) -> None:
    await set_ttl(session_id, ttl_seconds or _DEFAULT_TTL_SECONDS)


async def acquire_lock(session_id: str, ttl_seconds: int = 5) -> Optional[str]:
    return await acquire_session_lock(session_id, ttl_seconds=ttl_seconds)


async def release_lock(session_id: str, token: str) -> None:
    await release_session_lock(session_id, token)


async def scan_active_sessions(limit: int = 100):
    count = 0
    async for key in redis_store.scan_iter(match="session:*"):
        if count >= limit:
            break
        yield key
        count += 1
