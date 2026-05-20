import logging

from .intent_classifier import (
    classify_intent,
    INTENT_APPOINTMENT_BOOKING,
    INTENT_EMERGENCY,
    INTENT_FALLBACK,
    INTENT_FOLLOW_UP,
    INTENT_GENERAL_INFO,
)
from .appointment_service import (
    handle_appointment_booking,
    extract_booking_context,
)
from .appointment_service import extract_name, extract_phone
from .appointment_service import handle_general_info
from .followup_service import handle_follow_up
from .emergency_service import handle_emergency

logger = logging.getLogger("clinic_voice_assistant.query_router")

STATE_IDLE = "idle"
STATE_PENDING_BOOKING = "pending_booking"
STATE_FOLLOW_UP = "follow_up"


def _merge_booking_context(base, update):
    merged = dict(base or {})
    for key, value in (update or {}).items():
        if value and value != "unknown":
            merged[key] = value
    return merged


def _build_booking_query(booking_context, query_text):
    parts = [query_text]
    doctor_name = booking_context.get("doctor_name")
    if doctor_name:
        parts.append(doctor_name)
    appointment_date = booking_context.get("appointment_date")
    if appointment_date:
        parts.append(appointment_date)
    appointment_time = booking_context.get("appointment_time")
    if appointment_time:
        parts.append(appointment_time)
    specialty = booking_context.get("specialty")
    if specialty:
        parts.append(specialty)
    patient_name = booking_context.get("patient_name")
    if patient_name and patient_name != "Unknown":
        parts.append(f"my name is {patient_name}")
    patient_phone = booking_context.get("patient_phone")
    if patient_phone and patient_phone != "unknown":
        parts.append(f"phone {patient_phone}")
    return " ".join(part for part in parts if part)


def process_query(query_text, session_context):
    session_context = session_context or {}
    pending_intent = session_context.get("pending_intent")

    if pending_intent == INTENT_APPOINTMENT_BOOKING:
        extracted = extract_booking_context(query_text)
        merged_context = _merge_booking_context(session_context.get("booking_context", {}), extracted)
        combined_query = _build_booking_query(merged_context, query_text)
        result = handle_appointment_booking(combined_query)
    else:
        intent = classify_intent(query_text)
        if intent == INTENT_GENERAL_INFO:
            result = handle_general_info(query_text)
        elif intent == INTENT_APPOINTMENT_BOOKING:
            result = handle_appointment_booking(query_text)
        elif intent == INTENT_FOLLOW_UP:
            result = handle_follow_up(query_text, extract_name(query_text), extract_phone(query_text))
        elif intent == INTENT_EMERGENCY:
            result = handle_emergency(query_text)
        else:
            result = {
                "intent": INTENT_FALLBACK,
                "response": (
                    "I can help with appointments, clinic info, follow-ups, or emergencies. "
                    "Please tell me what you need in a bit more detail."
                ),
                "actions": {
                    "saved": False,
                    "hint": "clarification_requested",
                    "query": query_text,
                },
            }

    actions = result.get("actions", {})
    if result.get("intent") == INTENT_APPOINTMENT_BOOKING and actions.get("missing_fields"):
        session_context["pending_intent"] = INTENT_APPOINTMENT_BOOKING
        session_context["booking_context"] = actions.get("extracted", {})
        session_context["missing_fields"] = actions.get("missing_fields", [])
    else:
        session_context["pending_intent"] = None
        session_context["booking_context"] = {}
        session_context["missing_fields"] = []

    _update_conversation_state(session_context, result)

    return result, session_context


def _update_conversation_state(session_context, result):
    state = dict(session_context.get("conversation_state") or {})
    intent = result.get("intent")
    actions = result.get("actions", {})
    missing_fields = actions.get("missing_fields", [])

    if intent == INTENT_APPOINTMENT_BOOKING and missing_fields:
        state["state"] = STATE_PENDING_BOOKING
        state["missing_fields"] = missing_fields
        state["pending_intent"] = INTENT_APPOINTMENT_BOOKING
    elif intent == INTENT_FOLLOW_UP:
        state["state"] = STATE_FOLLOW_UP
        state["missing_fields"] = []
        state["pending_intent"] = None
    else:
        state["state"] = STATE_IDLE
        state["missing_fields"] = []
        state["pending_intent"] = None

    state["last_intent"] = intent
    state["last_action"] = actions.get("hint") or actions.get("reason")
    session_context["conversation_state"] = state
