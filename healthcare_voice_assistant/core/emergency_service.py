import logging

from .appointment_service import get_clinic_info
from .followup_service import save_query_result
from .appointment_service import extract_phone

logger = logging.getLogger("clinic_voice_assistant.emergency_service")


def handle_emergency(query_text):
    _ = save_query_result(
        caller_phone=extract_phone(query_text),
        query_type="emergency",
        query_details=query_text,
        resolution_status="escalated",
    )

    emergency_info = get_clinic_info("emergency")
    emergency_number = (
        emergency_info.get("value", "Call 911 immediately.")
        if emergency_info.get("success")
        else "Call 911 immediately."
    )

    return {
        "intent": "emergency",
        "response": (
            "This sounds like an emergency. Please call 911 immediately or go to the nearest emergency room now. "
            + emergency_number
        ),
        "actions": {
            "escalated": True,
            "emergency_advice_given": True,
        },
    }
