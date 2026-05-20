import asyncio
import logging
from typing import Awaitable, Callable, Dict, Optional

from .realtime_orchestrator import OrchestratorConfig, RealtimeOrchestrator
from .realtime_pipeline import PipelineConfig, RealtimeSpeechPipeline, TranscriptHandler

logger = logging.getLogger("voice_gateway.session_coordinator")

ChunkHandler = Callable[[bytes, str, int], Awaitable[None]]


class SessionCoordinator:
    def __init__(self, config: OrchestratorConfig, pipeline_config: PipelineConfig) -> None:
        self._config = config
        self._pipeline_config = pipeline_config
        self._sessions: Dict[str, RealtimeOrchestrator] = {}
        self._pipelines: Dict[str, RealtimeSpeechPipeline] = {}
        self._lock = asyncio.Lock()

    async def get_or_create(self, call_sid: str, on_chunk: Optional[ChunkHandler] = None) -> RealtimeOrchestrator:
        async with self._lock:
            if call_sid not in self._sessions:
                self._sessions[call_sid] = RealtimeOrchestrator(call_sid, self._config, on_chunk=on_chunk)
            elif on_chunk:
                self._sessions[call_sid].set_on_chunk(on_chunk)
            return self._sessions[call_sid]

    async def get_or_create_pipeline(
        self,
        call_sid: str,
        on_transcript: Optional[TranscriptHandler] = None,
    ) -> RealtimeSpeechPipeline:
        async with self._lock:
            if call_sid not in self._pipelines:
                self._pipelines[call_sid] = RealtimeSpeechPipeline(
                    call_sid,
                    self._pipeline_config,
                    on_transcript=on_transcript,
                )
            elif on_transcript:
                self._pipelines[call_sid].set_on_transcript(on_transcript)
            return self._pipelines[call_sid]

    async def reset(self, call_sid: str) -> None:
        async with self._lock:
            orchestrator = self._sessions.get(call_sid)
            pipeline = self._pipelines.get(call_sid)
        if orchestrator:
            await orchestrator.reset()
        if pipeline:
            await pipeline.reset()

    async def remove(self, call_sid: str) -> None:
        async with self._lock:
            orchestrator = self._sessions.pop(call_sid, None)
            pipeline = self._pipelines.pop(call_sid, None)
        if orchestrator:
            await orchestrator.reset()
        if pipeline:
            await pipeline.stop()

    async def active_sessions(self) -> int:
        async with self._lock:
            return len(self._sessions)
