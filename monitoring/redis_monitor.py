import os
from typing import Dict

import redis.asyncio as redis

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


async def check_redis() -> Dict[str, str]:
    client = redis.from_url(_REDIS_URL, decode_responses=True)
    try:
        await client.ping()
        return {"status": "ok", "url": _REDIS_URL}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}
