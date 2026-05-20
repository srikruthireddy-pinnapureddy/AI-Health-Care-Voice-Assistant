import asyncio
import os
from typing import Any, AsyncIterator, Optional

import redis.asyncio as redis

_REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
_REDIS_CLIENT: Optional[redis.Redis] = None
_REDIS_LOCK = asyncio.Lock()


async def get_redis() -> redis.Redis:
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT

    async with _REDIS_LOCK:
        if _REDIS_CLIENT is None:
            _REDIS_CLIENT = redis.from_url(_REDIS_URL, decode_responses=True)
    return _REDIS_CLIENT


async def get_value(key: str) -> Optional[str]:
    client = await get_redis()
    return await client.get(key)


async def set_value(key: str, value: str, ttl_seconds: int) -> None:
    client = await get_redis()
    await client.setex(key, ttl_seconds, value)


async def expire(key: str, ttl_seconds: int) -> None:
    client = await get_redis()
    await client.expire(key, ttl_seconds)


async def delete(key: str) -> None:
    client = await get_redis()
    await client.delete(key)


async def scan_iter(match: str) -> AsyncIterator[str]:
    client = await get_redis()
    async for key in client.scan_iter(match=match):
        yield key


async def set_lock(key: str, token: str, ttl_seconds: int) -> bool:
    client = await get_redis()
    ok = await client.set(key, token, nx=True, ex=ttl_seconds)
    return bool(ok)


async def release_lock(key: str, token: str) -> None:
    client = await get_redis()
    script = (
        "if redis.call('get', KEYS[1]) == ARGV[1] "
        "then return redis.call('del', KEYS[1]) else return 0 end"
    )
    await client.eval(script, 1, key, token)


async def compare_and_set_json(
    key: str,
    value_json: str,
    ttl_seconds: int,
    expected_version: int,
) -> bool:
    client = await get_redis()
    script = (
        "local current = redis.call('get', KEYS[1]) "
        "if not current then "
        "redis.call('setex', KEYS[1], ARGV[2], ARGV[1]) "
        "return 1 end "
        "local obj = cjson.decode(current) "
        "local version = tonumber(obj['session_version'] or 0) "
        "if version ~= tonumber(ARGV[3]) then return 0 end "
        "redis.call('setex', KEYS[1], ARGV[2], ARGV[1]) "
        "return 1"
    )
    result = await client.eval(script, 1, key, value_json, ttl_seconds, expected_version)
    return result == 1
