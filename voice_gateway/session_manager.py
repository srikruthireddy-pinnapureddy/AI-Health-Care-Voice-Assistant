import json
from dataclasses import asdict, dataclass
from typing import Optional

import redis.asyncio as redis

from config import settings


@dataclass
class SessionState:
    call_sid: str
    language: str
    conversation_state: str


class SessionManager:
    def __init__(self) -> None:
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)

    async def initialize(self, call_sid: str, language: str) -> SessionState:
        state = SessionState(
            call_sid=call_sid,
            language=language,
            conversation_state="initialized",
        )
        await self._redis.set(self._key(call_sid), json.dumps(asdict(state)))
        return state

    async def get(self, call_sid: str) -> Optional[SessionState]:
        raw = await self._redis.get(self._key(call_sid))
        if raw is None:
            return None
        data = json.loads(raw)
        return SessionState(**data)

    async def update(self, state: SessionState) -> None:
        await self._redis.set(self._key(state.call_sid), json.dumps(asdict(state)))

    async def set_conversation_state(self, call_sid: str, state: str) -> None:
        existing = await self.get(call_sid)
        if existing is None:
            return
        updated = SessionState(
            call_sid=existing.call_sid,
            language=existing.language,
            conversation_state=state,
        )
        await self.update(updated)

    async def close(self) -> None:
        await self._redis.close()

    @staticmethod
    def _key(call_sid: str) -> str:
        return f"voice_gateway:session:{call_sid}"
