import logging
from typing import Optional

from fastapi import APIRouter, HTTPException

from healthcare_voice_assistant.core.async_query_router import (
    cleanup_expired_sessions,
    get_session_context,
)
from session import session_manager
from healthcare_voice_assistant.metrics.metrics_collector import get_metrics_collector

logger = logging.getLogger("voice_gateway.observability")
router = APIRouter()


@router.get("/metrics")
async def metrics_snapshot() -> dict:
    collector = get_metrics_collector()
    return collector.get_snapshot()


@router.get("/active-calls")
async def active_calls(limit: int = 100) -> dict:
    calls = []
    async for key in session_manager.scan_active_sessions(limit=limit):
        session_id = key.split(":", 1)[-1]
        context = await get_session_context(session_id)
        calls.append(context)
    return {"count": len(calls), "calls": calls}


@router.get("/session/{call_sid}")
async def session_details(call_sid: str) -> dict:
    context = await get_session_context(call_sid)
    if not context:
        raise HTTPException(status_code=404, detail="Session not found")
    return context


@router.get("/session/{call_sid}/trace")
async def session_trace(call_sid: str) -> dict:
    collector = get_metrics_collector()
    return {"call_sid": call_sid, "trace": collector.get_call_trace(call_sid)}


@router.post("/metrics/cleanup")
async def cleanup_sessions(max_age_seconds: Optional[int] = None) -> dict:
    deleted = await cleanup_expired_sessions(max_age_seconds=max_age_seconds)
    return {"deleted": deleted}
