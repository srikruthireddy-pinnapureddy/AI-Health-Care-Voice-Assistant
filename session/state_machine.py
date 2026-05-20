from typing import Dict, Optional

from healthcare_voice_assistant.core.intent_classifier import (
    INTENT_APPOINTMENT_BOOKING,
    INTENT_EMERGENCY,
    INTENT_FOLLOW_UP,
)

STATE_IDLE = "idle"
STATE_GREETING = "greeting"
STATE_COLLECTING_DOCTOR = "collecting_doctor"
STATE_COLLECTING_DATE = "collecting_date"
STATE_COLLECTING_TIME = "collecting_time"
STATE_COLLECTING_PHONE = "collecting_phone"
STATE_CONFIRMATION = "confirmation"
STATE_BOOKING_COMPLETE = "booking_complete"
STATE_EMERGENCY_FLOW = "emergency_flow"
STATE_FOLLOWUP_FLOW = "followup_flow"


def resolve_state(session_context: Dict, result: Dict) -> str:
    intent = result.get("intent")
    actions = result.get("actions", {})

    if intent == INTENT_EMERGENCY:
        return STATE_EMERGENCY_FLOW
    if intent == INTENT_FOLLOW_UP:
        return STATE_FOLLOWUP_FLOW

    if intent == INTENT_APPOINTMENT_BOOKING:
        if actions.get("booked") is True:
            return STATE_BOOKING_COMPLETE
        missing = actions.get("missing_fields") or []
        if missing:
            if "doctor_name" in missing or "specialty" in missing:
                return STATE_COLLECTING_DOCTOR
            if "appointment_date" in missing:
                return STATE_COLLECTING_DATE
            if "appointment_time" in missing:
                return STATE_COLLECTING_TIME
            if "patient_phone" in missing:
                return STATE_COLLECTING_PHONE
        if actions.get("booked") is False:
            return STATE_CONFIRMATION

    return session_context.get("current_state") or STATE_IDLE
