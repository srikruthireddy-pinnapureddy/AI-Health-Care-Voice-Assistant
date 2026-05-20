import json
import time
from typing import Optional

from . import redis_store


async def cleanup_expired_sessions(max_age_seconds: int, match: str = "session:*") -> int:
    now = int(time.time())
    deleted = 0

    async for key in redis_store.scan_iter(match=match):
        raw = await redis_store.get_value(key)
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        last_activity = payload.get("last_activity_timestamp")
        if last_activity is None:
            continue
        if now - int(last_activity) > max_age_seconds:
            await redis_store.delete(key)
            deleted += 1

    return deleted
