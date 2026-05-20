import asyncio
from typing import Tuple

from .appointment_service import handle_appointment_booking, handle_general_info
from .emergency_service import handle_emergency
from .followup_service import handle_follow_up
from .query_router import process_query


async def process_query_async(query_text: str, session_context: dict) -> Tuple[dict, dict]:
    return await asyncio.to_thread(process_query, query_text, session_context)


async def handle_general_info_async(query_text: str) -> dict:
    return await asyncio.to_thread(handle_general_info, query_text)


async def handle_appointment_booking_async(query_text: str) -> dict:
    return await asyncio.to_thread(handle_appointment_booking, query_text)


async def handle_follow_up_async(query_text: str, patient_name: str, patient_phone: str) -> dict:
    return await asyncio.to_thread(handle_follow_up, query_text, patient_name, patient_phone)


async def handle_emergency_async(query_text: str) -> dict:
    return await asyncio.to_thread(handle_emergency, query_text)
