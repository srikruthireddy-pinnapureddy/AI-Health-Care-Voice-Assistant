import logging
import re

from flask import Blueprint, jsonify, request

from ..core.query_router import process_query
from ..core.translation_service import (
    LANG_EN,
    SUPPORTED_LANGUAGES,
    LANGUAGE_CONFIRMATION,
    LANGUAGE_OPTIONS,
    LANGUAGE_PROMPT,
    LANGUAGE_RETRY,
    detect_language_choice,
    translate_from_english,
    translate_to_english,
)
from ..core.intent_classifier import INTENT_FALLBACK, INTENT_LANGUAGE_SELECTION
from ..database.db import ensure_bootstrap
from ..core.session_store import get_session_context, save_session_context
from ..core.appointment_service import (
    get_doctors_by_specialty,
    get_total_doctor_count,
    get_available_slots,
    check_slot,
    is_time_within_availability,
    save_booking,
    normalize_time_str,
    cancel_booking_record,
    reschedule_booking_record,
    get_or_create_patient,
)
from ..core.followup_service import save_query_result

text_routes = Blueprint("text_routes", __name__)
logger = logging.getLogger("clinic_voice_assistant.text_routes")


def pick_first(payload, keys, default=""):
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def get_session_key(payload):
    explicit_session = pick_first(payload, ["session_id", "sessionId", "conversation_id", "conversationId"])
    if explicit_session:
        return explicit_session

    phone = re.sub(
        r"[^\d+]",
        "",
        pick_first(payload, ["patient_phone", "phone", "caller_phone", "contact", "number"], default=""),
    )
    if phone:
        return f"phone:{phone}"

    remote_addr = request.remote_addr or "anonymous"
    return f"ip:{remote_addr}"


def get_request_payload():
    payload = request.get_json(silent=True)
    if not payload:
        payload = request.form.to_dict(flat=True) if request.form else {}
    if not payload:
        payload = request.args.to_dict(flat=True) if request.args else {}
    return payload or {}


@text_routes.route("/route_query", methods=["POST"])
def route_query():
    try:
        ensure_bootstrap()
        payload = get_request_payload()
        query_text = pick_first(payload, ["query", "message", "text"]).strip()
        session_id = get_session_key(payload)
        session_context = get_session_context(session_id)
        selected_language = session_context.get("language")

        if not selected_language:
            if not query_text:
                session_context["language_prompted"] = True
                save_session_context(session_id, session_context)
                return jsonify(
                    {
                        "intent": INTENT_LANGUAGE_SELECTION,
                        "language": LANG_EN,
                        "response": LANGUAGE_PROMPT,
                        "options": LANGUAGE_OPTIONS,
                        "actions": {"selection_required": True},
                    }
                ), 200

            detected_choice = detect_language_choice(query_text)
            if not detected_choice:
                prompted_before = bool(session_context.get("language_prompted"))
                session_context["language_prompted"] = True
                save_session_context(session_id, session_context)
                actions = {"selection_required": True}
                if prompted_before:
                    actions["error"] = "unknown_language_choice"
                return jsonify(
                    {
                        "intent": INTENT_LANGUAGE_SELECTION,
                        "language": LANG_EN,
                        "response": LANGUAGE_RETRY if prompted_before else LANGUAGE_PROMPT,
                        "options": LANGUAGE_OPTIONS,
                        "actions": actions,
                    }
                ), 200

            session_context["language"] = detected_choice
            session_context["language_prompted"] = True
            save_session_context(session_id, session_context)
            logger.info("Language selected | session=%s language=%s", session_id, detected_choice)
            return jsonify(
                {
                    "intent": INTENT_LANGUAGE_SELECTION,
                    "language": detected_choice,
                    "response": LANGUAGE_CONFIRMATION.get(detected_choice, LANGUAGE_CONFIRMATION[LANG_EN]),
                    "actions": {"selection_required": False, "language_saved": True},
                }
            ), 200

        switch_choice = detect_language_choice(query_text) if query_text else None
        if switch_choice and switch_choice in SUPPORTED_LANGUAGES and switch_choice != selected_language:
            session_context["language"] = switch_choice
            save_session_context(session_id, session_context)
            logger.info("Language switched | session=%s language=%s", session_id, switch_choice)
            return jsonify(
                {
                    "intent": INTENT_LANGUAGE_SELECTION,
                    "language": switch_choice,
                    "response": LANGUAGE_CONFIRMATION.get(switch_choice, LANGUAGE_CONFIRMATION[LANG_EN]),
                    "actions": {"selection_required": False, "language_saved": True, "language_switched": True},
                }
            ), 200

        if not query_text:
            prompt = translate_from_english("Please provide a valid query in natural language.", selected_language)
            return jsonify(
                {
                    "intent": INTENT_FALLBACK,
                    "language": selected_language,
                    "response": prompt,
                    "actions": {"error": "missing_or_invalid_query"},
                }
            ), 400

        query_in_english = translate_to_english(query_text, selected_language)
        logger.info(
            "Incoming query after translation | session=%s language=%s raw_query=%s translated_query=%s",
            session_id,
            selected_language,
            query_text,
            query_in_english,
        )

        result, session_context = process_query(query_in_english, session_context)
        response_in_english = result.get("response", "")
        localized_response = translate_from_english(response_in_english, selected_language)

        result["language"] = selected_language
        result["response"] = localized_response
        save_session_context(session_id, session_context)

        return jsonify(result), 200

    except Exception:
        logger.exception("Unhandled error in /route_query")
        return jsonify(
            {
                "intent": INTENT_FALLBACK,
                "response": "Sorry, something went wrong while processing your request.",
                "actions": {"error": "internal_server_error"},
            }
        ), 500


@text_routes.route("/get_doctors_by_specialty", methods=["POST"])
def api_get_doctors_by_specialty():
    ensure_bootstrap()
    payload = get_request_payload()
    specialty = pick_first(payload, ["specialty", "department", "query_type"])

    if not specialty:
        return jsonify(
            {
                "success": False,
                "error": "Missing specialty",
                "accepted_fields": ["specialty", "department", "query_type"],
            }
        ), 200

    doctors = get_doctors_by_specialty(specialty)
    if not doctors and get_total_doctor_count() == 0:
        return jsonify({"success": False, "error": "No doctors found because doctors table is empty", "doctors": []}), 200

    return jsonify({"success": True, "specialty": specialty, "doctors": doctors}), 200


@text_routes.route("/check_slot", methods=["POST"])
def api_check_slot():
    ensure_bootstrap()
    payload = get_request_payload()
    doctor_name = pick_first(payload, ["doctor_name", "doctor", "doctorName"])
    appointment_date = pick_first(payload, ["appointment_date", "date", "appointmentDate"])
    appointment_time = normalize_time_str(
        pick_first(payload, ["appointment_time", "time", "slot_time", "appointmentTime"])
    )

    if not doctor_name or not appointment_date:
        return jsonify(
            {
                "success": False,
                "error": "Missing doctor_name or appointment_date",
                "accepted_fields": {
                    "doctor": ["doctor_name", "doctor", "doctorName"],
                    "date": ["appointment_date", "date", "appointmentDate"],
                    "time": ["appointment_time", "time", "slot_time", "appointmentTime"],
                },
            }
        ), 200

    available_slots = get_available_slots(doctor_name, appointment_date)
    if appointment_time:
        slot_info = check_slot(doctor_name, appointment_date, appointment_time)
        slot_available = slot_info.get("slot_available") and is_time_within_availability(
            doctor_name, appointment_date, appointment_time
        )
    else:
        slot_available = False

    return jsonify(
        {
            "success": True,
            "doctor_name": doctor_name,
            "appointment_date": appointment_date,
            "appointment_time": appointment_time,
            "slot_available": slot_available,
            "available_slots": available_slots,
            "available": slot_available,
        }
    ), 200


@text_routes.route("/save_booking", methods=["POST"])
def api_save_booking():
    ensure_bootstrap()
    payload = get_request_payload()

    doctor_name = pick_first(payload, ["doctor_name", "doctor", "doctorName"])
    appointment_date = pick_first(payload, ["appointment_date", "date", "appointmentDate"])
    appointment_time = normalize_time_str(
        pick_first(payload, ["appointment_time", "time", "slot_time", "appointmentTime"])
    )
    patient_name = pick_first(payload, ["patient_name", "name", "caller_name"], default="Unknown")
    raw_phone = pick_first(payload, ["patient_phone", "phone", "caller_phone", "contact", "number"])
    patient_phone = re.sub(r"[\s\-]", "", raw_phone)

    if not doctor_name or not appointment_date or not appointment_time or not patient_name or not patient_phone:
        return jsonify(
            {
                "success": False,
                "message": "Missing required booking fields",
                "accepted_fields": {
                    "doctor": ["doctor_name", "doctor", "doctorName"],
                    "date": ["appointment_date", "date", "appointmentDate"],
                    "time": ["appointment_time", "time", "slot_time", "appointmentTime"],
                    "patient_name": ["patient_name", "name", "caller_name"],
                    "patient_phone": ["patient_phone", "phone", "caller_phone", "contact", "number"],
                },
            }
        ), 200

    available_slots = get_available_slots(doctor_name, appointment_date)

    if not is_time_within_availability(doctor_name, appointment_date, appointment_time):
        return jsonify(
            {
                "success": False,
                "message": "Selected time is outside doctor availability",
                "available_slots": available_slots,
            }
        ), 400
    slot_status = check_slot(doctor_name, appointment_date, appointment_time)

    if not slot_status.get("slot_available"):
        return jsonify(
            {
                "success": False,
                "message": "Slot already booked",
                "available_slots": slot_status.get("available_slots"),
            }
        ), 200
    result = save_booking(patient_name, patient_phone, doctor_name, appointment_date, appointment_time)
    if not result.get("success"):
        return jsonify(
            {
                "success": False,
                "message": result.get("message", "Booking failed"),
                "available_slots": available_slots,
            }
        ), 200

    return jsonify(
        {
            "success": True,
            "appointment_id": result.get("appointment_id"),
            "doctor_name": doctor_name,
            "appointment_date": appointment_date,
            "appointment_time": appointment_time,
            "patient_name": patient_name,
            "patient_phone": patient_phone,
        }
    ), 200


@text_routes.route("/cancel_booking", methods=["POST"])
def api_cancel_booking():
    ensure_bootstrap()
    payload = get_request_payload()

    patient_phone = re.sub(
        r"[\s\-]",
        "",
        pick_first(payload, ["patient_phone", "phone", "caller_phone", "contact", "number"]),
    )
    doctor_name = pick_first(payload, ["doctor_name", "doctor", "doctorName"])
    appointment_date = pick_first(payload, ["appointment_date", "date", "appointmentDate"])
    appointment_time = normalize_time_str(
        pick_first(payload, ["appointment_time", "time", "slot_time", "appointmentTime"])
    )

    if not patient_phone or not doctor_name or not appointment_date or not appointment_time:
        return jsonify(
            {
                "success": False,
                "message": "Missing required cancellation fields",
                "accepted_fields": {
                    "patient_phone": ["patient_phone", "phone", "caller_phone", "contact", "number"],
                    "doctor": ["doctor_name", "doctor", "doctorName"],
                    "date": ["appointment_date", "date", "appointmentDate"],
                    "time": ["appointment_time", "time", "slot_time", "appointmentTime"],
                },
            }
        ), 200

    result = cancel_booking_record(patient_phone, doctor_name, appointment_date, appointment_time)
    if not result.get("success"):
        return jsonify({"success": False, "message": result.get("message", "No active booking found")}), 200

    return jsonify({"success": True, "message": "Appointment cancelled successfully"}), 200


@text_routes.route("/reschedule_booking", methods=["POST"])
def api_reschedule_booking():
    ensure_bootstrap()
    payload = get_request_payload()

    patient_phone = re.sub(
        r"[\s\-]",
        "",
        pick_first(payload, ["patient_phone", "phone", "caller_phone", "contact", "number"]),
    )
    doctor_name = pick_first(payload, ["doctor_name", "doctor", "doctorName"])
    old_date = pick_first(payload, ["old_date", "from_date", "previous_date"])
    old_time = normalize_time_str(pick_first(payload, ["old_time", "from_time", "previous_time"]))
    new_date = pick_first(payload, ["new_date", "to_date", "date"])
    new_time = normalize_time_str(pick_first(payload, ["new_time", "to_time", "time"]))

    if not patient_phone or not doctor_name or not old_date or not old_time or not new_date or not new_time:
        return jsonify(
            {
                "success": False,
                "message": "Missing required reschedule fields",
                "accepted_fields": {
                    "patient_phone": ["patient_phone", "phone", "caller_phone", "contact", "number"],
                    "doctor": ["doctor_name", "doctor", "doctorName"],
                    "old_date": ["old_date", "from_date", "previous_date"],
                    "old_time": ["old_time", "from_time", "previous_time"],
                    "new_date": ["new_date", "to_date", "date"],
                    "new_time": ["new_time", "to_time", "time"],
                },
            }
        ), 200

    result = reschedule_booking_record(patient_phone, doctor_name, old_date, old_time, new_date, new_time)
    if not result.get("success"):
        message = result.get("message", "Unable to reschedule booking")
        return jsonify(
            {
                "success": False,
                "message": message,
                "available_slots": result.get("available_slots", []),
            }
        ), 200

    return jsonify({"success": True, "message": "Appointment rescheduled successfully"}), 200


@text_routes.route("/get_or_create_patient", methods=["POST"])
def api_get_or_create_patient():
    ensure_bootstrap()
    payload = get_request_payload()

    patient_name = (
        payload.get("patient_name") or payload.get("name") or payload.get("caller_name") or "Unknown"
    ).strip()

    raw_phone = (
        payload.get("phone")
        or payload.get("patient_phone")
        or payload.get("caller_phone")
        or payload.get("contact")
        or payload.get("number")
        or ""
    )
    phone = re.sub(r"[\s\-]", "", str(raw_phone).strip())

    if not phone:
        logger.warning("get_or_create_patient missing phone. payload_keys=%s", list(payload.keys()))
        return jsonify(
            {
                "success": False,
                "error": "Missing phone",
                "accepted_fields": ["phone", "patient_phone", "caller_phone", "contact", "number"],
            }
        ), 200

    result = get_or_create_patient(patient_name, phone)
    if not result.get("success"):
        return jsonify({"success": False, "error": result.get("message", "Unable to process patient")}), 500

    patient = result.get("patient") or {}
    return jsonify(
        {
            "success": True,
            "created": result.get("created", False),
            "patient_id": patient.get("id"),
            "patient_name": patient.get("patient_name"),
            "phone": patient.get("phone"),
            "created_at": patient.get("created_at"),
        }
    ), 200


@text_routes.route("/save_query_result", methods=["POST"])
def api_save_query_result():
    ensure_bootstrap()
    payload = get_request_payload()

    caller_phone = pick_first(payload, ["caller_phone", "phone", "patient_phone", "contact", "number"], default="unknown")
    query_type = pick_first(payload, ["query_type", "type", "intent"], default="general")
    query_details = pick_first(payload, ["query_details", "details", "query", "message"], default="")
    resolution_status = pick_first(payload, ["resolution_status", "status", "result"], default="unresolved")

    result = save_query_result(
        caller_phone=caller_phone,
        query_type=query_type,
        query_details=query_details,
        resolution_status=resolution_status,
    )
    if not result.get("success"):
        return jsonify({"success": False, "message": result.get("message", "Failed to save query")}), 500

    return jsonify({"success": True, "call_id": result.get("call_id")}), 200
