import json
import logging
import os
import threading

import redis

logger = logging.getLogger("clinic_voice_assistant.session_store")

_DEFAULT_TTL = 60 * 30


class RedisSessionStore:
    def __init__(self, redis_client, ttl_seconds=_DEFAULT_TTL):
        self._redis = redis_client
        self._ttl = ttl_seconds

    def get_context(self, session_id):
        key = f"session:{session_id}"
        raw = self._redis.get(key)
        if not raw:
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

        try:
            payload = json.loads(raw)
        except Exception:
            logger.exception("Failed to decode session context for %s", session_id)
            payload = {}

        payload.setdefault("session_id", session_id)
        payload.setdefault("call_sid", session_id)
        payload.setdefault("websocket_id", None)
        payload.setdefault("current_state", "idle")
        payload.setdefault("language", None)
        payload.setdefault("pending_intent", None)
        payload.setdefault("booking_context", {})
        payload.setdefault("missing_fields", [])
        payload.setdefault("conversation_state", {})
        payload.setdefault("last_activity_timestamp", None)
        payload.setdefault("interruption_state", {})
        payload.setdefault("interaction_history", [])
        payload.setdefault("last_assistant_response", None)
        payload.setdefault("playback_state", {})
        payload.setdefault("session_version", 0)
        return payload

    def save_context(self, session_id, context):
        key = f"session:{session_id}"
        payload = json.dumps(context)
        self._redis.setex(key, self._ttl, payload)


class InMemorySessionStore:
    def __init__(self):
        self._store = {}
        self._lock = threading.Lock()

    def get_context(self, session_id):
        with self._lock:
            return self._store.get(session_id, {
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
            }).copy()

    def save_context(self, session_id, context):
        with self._lock:
            self._store[session_id] = dict(context)


_SESSION_STORE = None


def init_session_store(app=None):
    global _SESSION_STORE
    ttl_seconds = int(os.getenv("SESSION_TTL_SECONDS", str(_DEFAULT_TTL)))
    redis_url = os.getenv("REDIS_URL")

    if redis_url:
        try:
            client = redis.from_url(redis_url, decode_responses=True)
            client.ping()
            _SESSION_STORE = RedisSessionStore(client, ttl_seconds=ttl_seconds)
            logger.info("Redis session store initialized")
            return
        except Exception:
            logger.exception("Failed to initialize Redis session store, falling back to memory")

    _SESSION_STORE = InMemorySessionStore()


def get_session_context(session_id):
    if _SESSION_STORE is None:
        init_session_store()
    return _SESSION_STORE.get_context(session_id)


def save_session_context(session_id, context):
    if _SESSION_STORE is None:
        init_session_store()
    _SESSION_STORE.save_context(session_id, context)
