import logging
import re
import sqlite3
from datetime import datetime, timedelta

from .intent_classifier import SPECIALTY_ALIASES, infer_info_key
from ..database.db import get_db, SLOT_INTERVAL_MINUTES

logger = logging.getLogger("clinic_voice_assistant.appointment_service")


def normalize_text(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def normalize_time_str(value):
    if not value:
        return None

    raw = str(value).strip().upper().replace(".", "")
    raw = re.sub(r"\s*(AM|PM)$", r" \1", raw)

    for fmt in ("%I:%M %p", "%I %p", "%H:%M", "%H"):
        try:
            return datetime.strptime(raw, fmt).strftime("%H:%M")
        except ValueError:
            continue
    return None


def extract_name(query_text):
    patterns = [
        r"\bmy name is\s+([a-zA-Z][a-zA-Z\s'-]{1,60})",
        r"\bi am\s+([a-zA-Z][a-zA-Z\s'-]{1,60})",
        r"\bthis is\s+([a-zA-Z][a-zA-Z\s'-]{1,60})",
    ]
    for pattern in patterns:
        match = re.search(pattern, query_text, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip(" ,.")
    return "Unknown"


def extract_phone(query_text):
    match = re.search(r"(\+?\d[\d\s\-\(\)\.]{6,}\d)", query_text)
    if not match:
        return "unknown"
    phone = re.sub(r"[\s\-\(\)\.]", "", match.group(1))
    return phone


def extract_doctor(query_text):
    match = re.search(r"\bdr\.?\s+[a-zA-Z]+(?:\s+[a-zA-Z]+){0,2}", query_text, flags=re.IGNORECASE)
    if match:
        doctor = match.group(0).strip()
        if not doctor.lower().startswith("dr"):
            return doctor
        cleaned = doctor.replace(".", "").strip()
        stop_words = {"today", "tomorrow", "at", "on", "for", "by", "available", "free"}
        parts = cleaned.split()
        while parts and parts[-1].lower() in stop_words:
            parts.pop()
        return " ".join(parts)
    return None


def extract_date(query_text):
    now = datetime.now()
    q = normalize_text(query_text)

    weekday_map = {
        "monday": 0,
        "tuesday": 1,
        "wednesday": 2,
        "thursday": 3,
        "friday": 4,
        "saturday": 5,
        "sunday": 6,
    }

    if "today" in q:
        return now.strftime("%Y-%m-%d")
    if "tomorrow" in q:
        return (now + timedelta(days=1)).strftime("%Y-%m-%d")
    if "next week" in q:
        return (now + timedelta(days=7)).strftime("%Y-%m-%d")

    for weekday, weekday_num in weekday_map.items():
        if re.search(rf"\bnext\s+{weekday}\b", q):
            days_ahead = ((weekday_num - now.weekday()) % 7) + 7
            return (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    for weekday, weekday_num in weekday_map.items():
        if re.search(rf"\b{weekday}\b", q):
            days_ahead = (weekday_num - now.weekday()) % 7
            if days_ahead == 0:
                days_ahead = 7
            return (now + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    date_patterns = [
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(\d{1,2}/\d{1,2}/\d{2,4})\b",
        r"\b(\d{1,2}-\d{1,2}-\d{2,4})\b",
    ]

    for pattern in date_patterns:
        match = re.search(pattern, query_text)
        if not match:
            continue
        raw = match.group(1)
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d-%m-%y", "%m/%d/%Y", "%m-%d-%Y"):
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
    return None


def extract_time(query_text):
    patterns = [
        r"\b(?:at\s*)?(\d{1,2}:\d{2}\s?(?:am|pm|AM|PM)?)\b",
        r"\b(?:at\s*)?(\d{1,2}\s?(?:am|pm|AM|PM))\b",
        r"\b(?:at\s*)(\d{1,2}:\d{2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, query_text)
        if match:
            return normalize_time_str(match.group(1))
    return None


def extract_specialty(query_text):
    q = normalize_text(query_text)
    for canonical_specialty, aliases in SPECIALTY_ALIASES.items():
        if any(alias in q for alias in aliases):
            return canonical_specialty
    return None


def extract_booking_context(query_text):
    return {
        "doctor_name": extract_doctor(query_text),
        "appointment_date": extract_date(query_text),
        "appointment_time": extract_time(query_text),
        "specialty": extract_specialty(query_text),
        "patient_name": extract_name(query_text),
        "patient_phone": extract_phone(query_text),
    }


def get_clinic_info(query_type):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT value FROM clinic_info WHERE key = ?", (query_type,))
        row = cur.fetchone()
        if not row:
            return {"success": False, "message": "Requested clinic information is unavailable."}
        return {"success": True, "key": query_type, "value": row["value"]}
    except Exception:
        logger.exception("Failed to fetch clinic info for key: %s", query_type)
        return {"success": False, "message": "Unable to retrieve clinic information right now."}
    finally:
        if conn:
            conn.close()


def get_doctors_by_specialty(specialty):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT doctor_name, specialty, phone, available_from, available_to
            FROM doctors
            WHERE LOWER(specialty) = LOWER(?)
            ORDER BY doctor_name
            """,
            (specialty,),
        )
        return [dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("Failed to get doctors by specialty: %s", specialty)
        return []
    finally:
        if conn:
            conn.close()


def get_total_doctor_count():
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS count FROM doctors")
        return cur.fetchone()["count"]
    except Exception:
        logger.exception("Failed to count doctors")
        return 0
    finally:
        if conn:
            conn.close()


def get_all_specialties():
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT specialty FROM doctors ORDER BY specialty")
        return [row["specialty"] for row in cur.fetchall()]
    except Exception:
        logger.exception("Failed to fetch specialties")
        return []
    finally:
        if conn:
            conn.close()


def get_canonical_doctor_name(doctor_name):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT doctor_name
            FROM doctors
            WHERE REPLACE(LOWER(doctor_name), '.', '') = REPLACE(LOWER(?), '.', '')
            LIMIT 1
            """,
            (doctor_name,),
        )
        row = cur.fetchone()
        return row["doctor_name"] if row else doctor_name
    except Exception:
        logger.exception("Failed to resolve canonical doctor name")
        return doctor_name
    finally:
        if conn:
            conn.close()


def get_availability_windows(doctor_name, available_date):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT start_time, end_time
            FROM doctor_availability
            WHERE REPLACE(LOWER(doctor_name), '.', '') = REPLACE(LOWER(?), '.', '')
              AND available_date = ?
            ORDER BY start_time
            """,
            (doctor_name, available_date),
        )
        return [dict(row) for row in cur.fetchall()]
    except Exception:
        logger.exception("Failed to fetch availability windows")
        return []
    finally:
        if conn:
            conn.close()


def is_time_within_availability(doctor_name, available_date, appointment_time):
    windows = get_availability_windows(doctor_name, available_date)
    if not windows:
        return False

    try:
        target_dt = datetime.strptime(appointment_time, "%H:%M")
    except ValueError:
        return False

    for window in windows:
        start_dt = datetime.strptime(window["start_time"], "%H:%M")
        end_dt = datetime.strptime(window["end_time"], "%H:%M")
        if start_dt <= target_dt < end_dt:
            return True
    return False


def format_time_human(time_24h):
    try:
        return datetime.strptime(time_24h, "%H:%M").strftime("%I:%M %p")
    except ValueError:
        return time_24h


def date_label(appointment_date):
    try:
        target = datetime.strptime(appointment_date, "%Y-%m-%d").date()
    except ValueError:
        return appointment_date

    today = datetime.now().date()
    if target == today + timedelta(days=1):
        return "tomorrow"
    if target == today:
        return "today"
    return appointment_date


def build_30_minute_slots(start_time, end_time):
    try:
        start_dt = datetime.strptime(start_time, "%H:%M")
        end_dt = datetime.strptime(end_time, "%H:%M")
    except ValueError:
        return []

    slots = []
    current_dt = start_dt
    while current_dt < end_dt:
        slots.append(current_dt.strftime("%H:%M"))
        current_dt += timedelta(minutes=SLOT_INTERVAL_MINUTES)
    return slots


def get_booked_slots(doctor_name, appointment_date):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT appointment_time
            FROM appointments
            WHERE REPLACE(LOWER(doctor_name), '.', '') = REPLACE(LOWER(?), '.', '')
              AND appointment_date = ?
              AND status = 'booked'
            """,
            (doctor_name, appointment_date),
        )
        booked = set()
        for row in cur.fetchall():
            normalized = normalize_time_str(row["appointment_time"])
            if normalized:
                booked.add(normalized)
        return booked
    except Exception:
        logger.exception(
            "Failed to get booked slots | doctor=%s date=%s",
            doctor_name,
            appointment_date,
        )
        return set()
    finally:
        if conn:
            conn.close()


def get_available_slots(doctor_name, appointment_date, limit=None):
    windows = get_availability_windows(doctor_name, appointment_date)
    if not windows:
        return []

    all_slots = []
    for window in windows:
        all_slots.extend(build_30_minute_slots(window["start_time"], window["end_time"]))

    booked_slots = get_booked_slots(doctor_name, appointment_date)
    free_slots = [slot for slot in all_slots if slot not in booked_slots]

    if limit is not None:
        return free_slots[:limit]
    return free_slots


def check_slot(doctor_name, appointment_date, appointment_time):
    normalized_time = normalize_time_str(appointment_time)
    if not normalized_time:
        return {
            "slot_available": False,
            "available_slots": [],
            "reason": "invalid_time",
        }

    available_slots = get_available_slots(doctor_name, appointment_date)
    return {
        "slot_available": normalized_time in available_slots,
        "available_slots": available_slots,
        "requested_time": normalized_time,
    }


def format_slots_for_voice(slots, limit=8):
    preview = slots[:limit]
    return ", ".join(format_time_human(slot) for slot in preview)


def suggest_alternative_slot(appointment_date, appointment_time, available_slots=None):
    if available_slots:
        return appointment_date, available_slots[0]

    conn = None
    try:
        normalized = normalize_time_str(appointment_time)
        if not normalized:
            return appointment_date, "12:00"

        base_dt = datetime.strptime(f"{appointment_date} {normalized}", "%Y-%m-%d %H:%M")
        alt_dt = base_dt + timedelta(minutes=SLOT_INTERVAL_MINUTES)
        return alt_dt.strftime("%Y-%m-%d"), alt_dt.strftime("%H:%M")
    except Exception:
        logger.exception("Failed to suggest alternate slot")
        return appointment_date, "12:00"
    finally:
        if conn:
            conn.close()


def find_first_available_slot(doctor_name, available_date):
    slots = get_available_slots(doctor_name, available_date, limit=1)
    return slots[0] if slots else None


def find_first_available_doctor_slot(specialty, available_date, preferred_time=None):
    doctors = get_doctors_by_specialty(specialty)
    for doctor in doctors:
        doctor_name = doctor["doctor_name"]

        if preferred_time and is_time_within_availability(doctor_name, available_date, preferred_time):
            if check_slot(doctor_name, available_date, preferred_time).get("slot_available"):
                return doctor_name, preferred_time

        first_time = find_first_available_slot(doctor_name, available_date)
        if first_time:
            return doctor_name, first_time

    return None, None


def save_booking(patient_name, patient_phone, doctor_name, appointment_date, appointment_time):
    conn = None
    try:
        canonical_doctor_name = get_canonical_doctor_name(doctor_name)
        appointment_time = normalize_time_str(appointment_time)
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO appointments
            (doctor_name, appointment_date, appointment_time, date, time, patient_name, patient_phone, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'booked', ?)
            """,
            (
                canonical_doctor_name,
                appointment_date,
                appointment_time,
                appointment_date,
                appointment_time,
                patient_name,
                patient_phone,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        return {"success": True, "appointment_id": cur.lastrowid}
    except sqlite3.IntegrityError:
        logger.warning(
            "Slot race condition detected while saving booking | doctor=%s date=%s time=%s",
            doctor_name,
            appointment_date,
            appointment_time,
        )
        return {"success": False, "message": "Selected slot is no longer available."}
    except Exception:
        logger.exception("Failed to save booking")
        return {"success": False, "message": "Unable to save booking right now."}
    finally:
        if conn:
            conn.close()


def get_or_create_patient(patient_name, phone):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT id, patient_name, phone, created_at FROM patients WHERE phone = ?",
            (phone,),
        )
        existing = cur.fetchone()
        if existing:
            return {"success": True, "created": False, "patient": dict(existing)}

        cur.execute(
            """
            INSERT INTO patients (patient_name, phone, created_at)
            VALUES (?, ?, ?)
            """,
            (patient_name, phone, datetime.utcnow().isoformat()),
        )
        conn.commit()

        cur.execute(
            "SELECT id, patient_name, phone, created_at FROM patients WHERE id = ?",
            (cur.lastrowid,),
        )
        created = cur.fetchone()
        return {"success": True, "created": True, "patient": dict(created) if created else None}
    except Exception:
        logger.exception("Failed to get/create patient")
        return {"success": False, "message": "Unable to process patient record."}
    finally:
        if conn:
            conn.close()


def cancel_booking_record(patient_phone, doctor_name, appointment_date, appointment_time):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE appointments
            SET status = 'cancelled'
            WHERE patient_phone = ?
              AND REPLACE(LOWER(doctor_name), '.', '') = REPLACE(LOWER(?), '.', '')
              AND appointment_date = ?
              AND appointment_time = ?
              AND status = 'booked'
            """,
            (patient_phone, doctor_name, appointment_date, appointment_time),
        )
        conn.commit()
        return {"success": cur.rowcount > 0}
    except Exception:
        logger.exception("Failed to cancel booking")
        return {"success": False, "message": "Unable to cancel booking."}
    finally:
        if conn:
            conn.close()


def reschedule_booking_record(patient_phone, doctor_name, old_date, old_time, new_date, new_time):
    if not is_time_within_availability(doctor_name, new_date, new_time):
        return {"success": False, "message": "Requested new time is outside doctor availability."}

    slot_status = check_slot(doctor_name, new_date, new_time)
    if not slot_status.get("slot_available"):
        return {
            "success": False,
            "message": "Requested new slot is not available.",
            "available_slots": slot_status.get("available_slots", [])[:8],
        }

    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE appointments
            SET appointment_date = ?, appointment_time = ?, date = ?, time = ?
            WHERE patient_phone = ?
              AND REPLACE(LOWER(doctor_name), '.', '') = REPLACE(LOWER(?), '.', '')
              AND appointment_date = ?
              AND appointment_time = ?
              AND status = 'booked'
            """,
            (new_date, new_time, new_date, new_time, patient_phone, doctor_name, old_date, old_time),
        )
        conn.commit()
        if cur.rowcount == 0:
            return {"success": False, "message": "No matching active booking found."}
        return {"success": True}
    except Exception:
        logger.exception("Failed to reschedule booking")
        return {"success": False, "message": "Unable to reschedule booking."}
    finally:
        if conn:
            conn.close()


def handle_general_info(query_text):
    key = infer_info_key(query_text)
    info = get_clinic_info(key)
    if not info.get("success"):
        return {
            "intent": "general_info",
            "response": "I could not fetch clinic information right now. Please try again shortly.",
            "actions": {"query_type": key, "success": False},
        }
    return {
        "intent": "general_info",
        "response": f"{key.capitalize()}: {info['value']}",
        "actions": {"query_type": key, "success": True, "value": info["value"]},
    }


def handle_appointment_booking(query_text):
    doctor_name = extract_doctor(query_text)
    appointment_date = extract_date(query_text)
    appointment_time = extract_time(query_text)
    specialty = extract_specialty(query_text)
    patient_name = extract_name(query_text)
    patient_phone = extract_phone(query_text)

    if not appointment_date:
        appointment_date = (datetime.now().date() + timedelta(days=1)).strftime("%Y-%m-%d")

    if doctor_name and not appointment_time:
        next_slots = get_available_slots(doctor_name, appointment_date, limit=6)
        if next_slots:
            return {
                "intent": "appointment_booking",
                "response": (
                    f"{doctor_name} is available {date_label(appointment_date)} at the following times: "
                    f"{format_slots_for_voice(next_slots, limit=6)}."
                ),
                "actions": {
                    "doctor": doctor_name,
                    "date": appointment_date,
                    "available_slots": next_slots,
                    "booked": False,
                },
            }

        return {
            "intent": "appointment_booking",
            "response": f"No free slots found for {doctor_name} on {appointment_date}.",
            "actions": {
                "doctor": doctor_name,
                "date": appointment_date,
                "available_slots": [],
                "booked": False,
            },
        }

    if not doctor_name and specialty:
        doctors = get_doctors_by_specialty(specialty)
        if not doctors:
            if get_total_doctor_count() == 0:
                return {
                    "intent": "appointment_booking",
                    "response": "No doctors found because the doctors table is empty. Please seed doctor records.",
                    "actions": {
                        "doctor": None,
                        "specialty": specialty,
                        "date": appointment_date,
                        "time": None,
                        "booked": False,
                    },
                }

            available_specialties = get_all_specialties()
            return {
                "intent": "appointment_booking",
                "response": (
                    f"I could not match '{specialty}' in our roster. "
                    f"Available specialties: {', '.join(available_specialties)}."
                ),
                "actions": {
                    "doctor": None,
                    "specialty": specialty,
                    "date": appointment_date,
                    "time": None,
                    "booked": False,
                    "available_specialties": available_specialties,
                },
            }

        suggested_doctor, suggested_time = find_first_available_doctor_slot(
            specialty=specialty,
            available_date=appointment_date,
            preferred_time=appointment_time,
        )

        if not suggested_doctor or not suggested_time:
            doctor_lines = []
            for doctor in doctors:
                windows = get_availability_windows(doctor["doctor_name"], appointment_date)
                if windows:
                    first_window = windows[0]["start_time"]
                    last_window = windows[-1]["end_time"]
                    doctor_lines.append(
                        f"{doctor['doctor_name']} — available {date_label(appointment_date)} {first_window}-{last_window}"
                    )

            response_line = (
                " ".join(doctor_lines)
                if doctor_lines
                else "Doctors are registered, but no availability slots are configured for that date."
            )
            return {
                "intent": "appointment_booking",
                "response": response_line,
                "actions": {
                    "doctor": None,
                    "specialty": specialty,
                    "date": appointment_date,
                    "time": None,
                    "booked": False,
                },
            }

        return {
            "intent": "appointment_booking",
            "response": (
                f"{suggested_doctor} is available {date_label(appointment_date)} at {format_time_human(suggested_time)}. "
                "Would you like to confirm?"
            ),
            "actions": {
                "doctor": suggested_doctor,
                "specialty": specialty,
                "date": appointment_date,
                "time": suggested_time,
                "booked": False,
            },
        }

    missing = []
    if not doctor_name:
        missing.append("doctor_name")
    if not appointment_time:
        missing.append("appointment_time")
    if patient_phone == "unknown":
        missing.append("patient_phone")

    if missing:
        return {
            "intent": "appointment_booking",
            "response": (
                "I can help with booking. Please provide missing details: " + ", ".join(missing) + "."
            ),
            "actions": {
                "booked": False,
                "missing_fields": missing,
                "extracted": {
                    "doctor_name": doctor_name,
                    "specialty": specialty,
                    "appointment_date": appointment_date,
                    "appointment_time": appointment_time,
                    "patient_name": patient_name,
                    "patient_phone": patient_phone,
                },
            },
        }

    doctor_name = get_canonical_doctor_name(doctor_name)

    slot_status = check_slot(doctor_name, appointment_date, appointment_time)
    is_free = slot_status.get("slot_available") and is_time_within_availability(
        doctor_name, appointment_date, appointment_time
    )

    if not is_free:
        available_slots = slot_status.get("available_slots", [])
        alt_date, alt_time = suggest_alternative_slot(appointment_date, appointment_time, available_slots)

        if available_slots:
            response_text = (
                f"{format_time_human(appointment_time)} is already booked. Available slots for {doctor_name} "
                f"{date_label(appointment_date)} are: {format_slots_for_voice(available_slots, limit=8)}."
            )
            suggested_alternative = {
                "appointment_date": alt_date,
                "appointment_time": alt_time,
            }
        else:
            response_text = (
                f"{format_time_human(appointment_time)} is not available for {doctor_name} "
                f"{date_label(appointment_date)}, and there are no open slots that day. "
                "Please choose another date."
            )
            suggested_alternative = None

        return {
            "intent": "appointment_booking",
            "response": response_text,
            "actions": {
                "booked": False,
                "reason": "slot_unavailable",
                "requested_slot": {
                    "doctor_name": doctor_name,
                    "appointment_date": appointment_date,
                    "appointment_time": appointment_time,
                },
                "suggested_alternative": suggested_alternative,
                "available_slots": available_slots,
            },
        }

    result = save_booking(
        patient_name=patient_name,
        patient_phone=patient_phone,
        doctor_name=doctor_name,
        appointment_date=appointment_date,
        appointment_time=appointment_time,
    )

    if not result.get("success"):
        return {
            "intent": "appointment_booking",
            "response": "I could not complete the booking right now. Please try again in a moment.",
            "actions": {"booked": False, "error": result.get("message", "unknown_error")},
        }

    return {
        "intent": "appointment_booking",
        "response": (
            f"Your appointment is confirmed with {doctor_name} on {appointment_date} at {format_time_human(appointment_time)}."
        ),
        "actions": {
            "booked": True,
            "appointment_id": result.get("appointment_id"),
            "doctor": doctor_name,
            "specialty": specialty,
            "date": appointment_date,
            "time": appointment_time,
            "patient_name": patient_name,
            "patient_phone": patient_phone,
        },
    }
