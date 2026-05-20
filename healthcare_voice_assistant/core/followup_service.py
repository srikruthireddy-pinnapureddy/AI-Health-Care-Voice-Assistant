import logging
from datetime import datetime, timedelta

from ..database.db import get_db

logger = logging.getLogger("clinic_voice_assistant.followup_service")


def save_query_result(caller_phone, query_type, query_details, resolution_status):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO calls (caller_phone, query_type, query_details, resolution_status, call_time)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                caller_phone,
                query_type,
                query_details,
                resolution_status,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        return {"success": True, "call_id": cur.lastrowid}
    except Exception:
        logger.exception("Failed to save query result")
        return {"success": False, "message": "Unable to log call right now."}
    finally:
        if conn:
            conn.close()


def save_follow_up(patient_name, patient_phone, query_description, followup_date=None, notes=""):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO followups (patient_name, patient_phone, query, followup_date, notes, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                patient_name,
                patient_phone,
                query_description,
                followup_date or datetime.now().strftime("%Y-%m-%d"),
                notes,
                datetime.utcnow().isoformat(),
            ),
        )
        conn.commit()
        return {"success": True, "followup_id": cur.lastrowid}
    except Exception:
        logger.exception("Failed to save follow-up")
        return {"success": False, "message": "Unable to save follow-up right now."}
    finally:
        if conn:
            conn.close()


def handle_follow_up(query_text, patient_name, patient_phone):
    call_log = save_query_result(
        caller_phone=patient_phone,
        query_type="follow_up",
        query_details=query_text,
        resolution_status="unresolved",
    )

    followup_log = save_follow_up(
        patient_name=patient_name,
        patient_phone=patient_phone,
        query_description=query_text,
        followup_date=(datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
        notes="Follow-up required from receptionist",
    )

    if not call_log.get("success") or not followup_log.get("success"):
        return {
            "intent": "follow_up",
            "response": "Your issue is noted, but there was a system problem saving the follow-up. Please call again shortly.",
            "actions": {
                "saved": False,
                "caller_phone": patient_phone,
                "patient_name": patient_name,
            },
        }

    return {
        "intent": "follow_up",
        "response": "I have logged your unresolved issue and requested a callback from our clinic team.",
        "actions": {
            "saved": True,
            "call_id": call_log.get("call_id"),
            "followup_id": followup_log.get("followup_id"),
            "patient_name": patient_name,
            "patient_phone": patient_phone,
            "followup_date": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"),
        },
    }
