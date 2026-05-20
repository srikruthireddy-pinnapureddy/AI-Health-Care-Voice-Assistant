from typing import Dict

from session import session_manager


async def get_active_calls(limit: int = 100) -> Dict[str, int]:
    count = 0
    async for _ in session_manager.scan_active_sessions(limit=limit):
        count += 1
    return {"count": count}
