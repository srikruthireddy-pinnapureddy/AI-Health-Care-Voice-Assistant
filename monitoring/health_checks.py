from typing import Dict

from .gpu_monitor import check_gpu
from .redis_monitor import check_redis


async def get_health() -> Dict[str, Dict[str, str]]:
    redis_status = await check_redis()
    gpu_status = check_gpu()
    overall = "ok" if redis_status.get("status") == "ok" else "degraded"
    return {
        "status": overall,
        "redis": redis_status,
        "gpu": gpu_status,
    }
