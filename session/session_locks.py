import uuid
from typing import Optional

from . import redis_store


def session_lock_key(session_id: str) -> str:
    return f"session:{session_id}:lock"


async def acquire_session_lock(session_id: str, ttl_seconds: int = 5) -> Optional[str]:
    token = uuid.uuid4().hex
    ok = await redis_store.set_lock(session_lock_key(session_id), token, ttl_seconds)
    return token if ok else None


async def release_session_lock(session_id: str, token: str) -> None:
    await redis_store.release_lock(session_lock_key(session_id), token)
