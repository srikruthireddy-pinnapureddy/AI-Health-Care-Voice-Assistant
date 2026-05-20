import asyncio
import logging
from typing import Dict, Optional

from fastapi import WebSocket

from .playback_queue import PlaybackItem, PlaybackQueue
from .streaming_tts import StreamingTTS, StreamingTTSConfig

logger = logging.getLogger("voice_gateway.playback_manager")


class PlaybackManager:
    def __init__(
        self,
        websocket: WebSocket,
        frame_duration_ms: int = 20,
        tts_config: StreamingTTSConfig | None = None,
    ) -> None:
        self._websocket = websocket
        self._frame_duration_ms = frame_duration_ms
        self._queues: Dict[str, PlaybackQueue] = {}
        self._tasks: Dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._tts = StreamingTTS(tts_config)

    async def enqueue(self, call_sid: str, stream_sid: str, ulaw_audio: bytes) -> None:
        frames = self._tts.encode_frames(ulaw_audio)
        async with self._lock:
            queue = self._queues.setdefault(call_sid, PlaybackQueue())
            await queue.put(PlaybackItem(stream_sid=stream_sid, frames=frames))
            if call_sid not in self._tasks:
                self._tasks[call_sid] = asyncio.create_task(self._play_loop(call_sid))

    async def cancel(self, call_sid: str) -> None:
        async with self._lock:
            queue = self._queues.get(call_sid)
            if queue:
                await queue.drain()
            task = self._tasks.pop(call_sid, None)
        if task:
            task.cancel()

    async def _play_loop(self, call_sid: str) -> None:
        queue = self._queues[call_sid]
        try:
            while True:
                item = await queue.get()
                for payload in item.frames:
                    await self._websocket.send_json(
                        {
                            "event": "media",
                            "streamSid": item.stream_sid,
                            "media": {"payload": payload},
                        }
                    )
                    await asyncio.sleep(self._frame_duration_ms / 1000)
        except asyncio.CancelledError:
            logger.info("Playback cancelled", extra={"call_sid": call_sid})
        except Exception:
            logger.exception("Playback loop failed", extra={"call_sid": call_sid})
