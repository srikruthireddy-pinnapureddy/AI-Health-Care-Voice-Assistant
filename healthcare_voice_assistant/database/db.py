import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timedelta

import redis

logger = logging.getLogger("clinic_voice_assistant.db")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_NAME = os.path.join(BASE_DIR, "clinic.db")

_BOOTSTRAPPED = False
SLOT_INTERVAL_MINUTES = 30
APPOINTMENTS_MIGRATION_STEPS = []

_REDIS_CLIENT = None
_REDIS_LOCK = threading.Lock()


def get_db():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def get_redis_client():
    global _REDIS_CLIENT
    if _REDIS_CLIENT is not None:
        return _REDIS_CLIENT
    with _REDIS_LOCK:
        if _REDIS_CLIENT is None:
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
            _REDIS_CLIENT = redis.from_url(redis_url, decode_responses=True)
    return _REDIS_CLIENT


def get_session_context(session_id):
    client = get_redis_client()
    key = f"session:{session_id}"
    raw = client.get(key)
    if not raw:
        return {
            "session_id": session_id,
            "language": None,
            "pending_intent": None,
            "booking_context": {},
            "missing_fields": [],
            "conversation_state": {},
        }

    try:
        payload = json.loads(raw)
    except Exception:
        logger.exception("Failed to decode session context for %s", session_id)
        payload = {}

    payload.setdefault("session_id", session_id)
    payload.setdefault("language", None)
    payload.setdefault("pending_intent", None)
    payload.setdefault("booking_context", {})
    payload.setdefault("missing_fields", [])
    payload.setdefault("conversation_state", {})
    return payload


def save_session_context(session_id, context, ttl_seconds=1800):
    client = get_redis_client()
    key = f"session:{session_id}"
    payload = json.dumps(context)
    client.setex(key, ttl_seconds, payload)


def init_db():
    global APPOINTMENTS_MIGRATION_STEPS
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS clinic_info (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_name TEXT NOT NULL,
            specialty TEXT NOT NULL,
            phone TEXT,
            available_from TEXT,
            available_to TEXT
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS doctor_availability (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doctor_name TEXT NOT NULL,
            available_date TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT NOT NULL,
            doctor_name TEXT NOT NULL,
            date TEXT,
            time TEXT,
            appointment_date TEXT,
            appointment_time TEXT,
            patient_phone TEXT,
            status TEXT NOT NULL DEFAULT 'booked',
            created_at TEXT
        )
        """
    )

    cur.execute("PRAGMA table_info(appointments)")
    appointment_columns = {row["name"] for row in cur.fetchall()}

    migration_steps = []
    if "date" not in appointment_columns:
        cur.execute("ALTER TABLE appointments ADD COLUMN date TEXT")
        migration_steps.append("Added appointments.date")
    if "time" not in appointment_columns:
        cur.execute("ALTER TABLE appointments ADD COLUMN time TEXT")
        migration_steps.append("Added appointments.time")
    if "created_at" not in appointment_columns:
        cur.execute("ALTER TABLE appointments ADD COLUMN created_at TEXT")
        migration_steps.append("Added appointments.created_at")

    cur.execute(
        """
        UPDATE appointments
        SET date = COALESCE(NULLIF(TRIM(date), ''), appointment_date)
        WHERE (date IS NULL OR TRIM(date) = '')
          AND appointment_date IS NOT NULL
          AND TRIM(appointment_date) <> ''
        """
    )
    cur.execute(
        """
        UPDATE appointments
        SET time = COALESCE(NULLIF(TRIM(time), ''), appointment_time)
        WHERE (time IS NULL OR TRIM(time) = '')
          AND appointment_time IS NOT NULL
          AND TRIM(appointment_time) <> ''
        """
    )
    cur.execute(
        """
        UPDATE appointments
        SET appointment_date = COALESCE(NULLIF(TRIM(appointment_date), ''), date)
        WHERE (appointment_date IS NULL OR TRIM(appointment_date) = '')
          AND date IS NOT NULL
          AND TRIM(date) <> ''
        """
    )
    cur.execute(
        """
        UPDATE appointments
        SET appointment_time = COALESCE(NULLIF(TRIM(appointment_time), ''), time)
        WHERE (appointment_time IS NULL OR TRIM(appointment_time) = '')
          AND time IS NOT NULL
          AND TRIM(time) <> ''
        """
    )
    cur.execute(
        """
        UPDATE appointments
        SET status = 'booked'
        WHERE status IS NULL
           OR LOWER(TRIM(status)) IN ('confirmed', 'booked', 'active')
        """
    )
    cur.execute(
        """
        UPDATE appointments
        SET status = 'cancelled'
        WHERE LOWER(TRIM(status)) IN ('canceled', 'cancelled')
        """
    )

    if migration_steps:
        migration_steps.append("Backfilled date/time and normalized status values")
    APPOINTMENTS_MIGRATION_STEPS = migration_steps

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT,
            phone TEXT UNIQUE,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_unique_slot
        ON appointments (doctor_name, appointment_date, appointment_time)
        WHERE status = 'booked'
        """
    )

    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_unique_slot_ci
        ON appointments (LOWER(doctor_name), appointment_date, appointment_time)
        WHERE status = 'booked'
        """
    )

    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_unique_slot_new_schema
        ON appointments (doctor_name, date, time)
        WHERE status = 'booked'
        """
    )

    cur.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_appointments_unique_slot_ci_new_schema
        ON appointments (LOWER(doctor_name), date, time)
        WHERE status = 'booked'
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            caller_phone TEXT,
            query_type TEXT,
            query_details TEXT,
            resolution_status TEXT,
            call_time TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS followups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_name TEXT,
            patient_phone TEXT,
            query TEXT,
            followup_date TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        )
        """
    )

    cur.execute("SELECT COUNT(*) AS count FROM clinic_info")
    row = cur.fetchone()
    if row and row["count"] == 0:
        seed_data = {
            "timings": "Mon-Sat, 9:00 AM to 7:00 PM",
            "location": "123 Health Street, Toronto",
            "services": "General Medicine, Cardiology, Pediatrics, Dermatology",
            "reports": "Reports can be collected from reception after 24 hours",
            "emergency": "Call 911 or our emergency desk at +1-416-555-0000",
            "phone": "+1-416-555-1234",
        }
        for key, value in seed_data.items():
            cur.execute("INSERT INTO clinic_info (key, value) VALUES (?, ?)", (key, value))

    conn.commit()
    conn.close()
    if APPOINTMENTS_MIGRATION_STEPS:
        logger.info("Appointments migration applied: %s", "; ".join(APPOINTMENTS_MIGRATION_STEPS))
    logger.info("Database initialized successfully")


def seed_doctors():
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) AS count FROM doctors")
        row = cur.fetchone()
        if row and row["count"] > 0:
            logger.info("Doctors already seeded")
            return

        doctors = [
            ("Dr. Sarah Sharma", "general physician", "+1-416-555-1001", "09:00", "17:00"),
            ("Dr. Raj Patel", "cardiologist", "+1-416-555-1002", "10:00", "16:00"),
            ("Dr. Ananya Reddy", "dermatologist", "+1-416-555-1003", "11:00", "18:00"),
            ("Dr. Michael Chen", "neurologist", "+1-416-555-1004", "09:30", "15:30"),
            ("Dr. Priya Nair", "pediatrician", "+1-416-555-1005", "08:30", "14:30"),
        ]

        cur.executemany(
            """
            INSERT INTO doctors (doctor_name, specialty, phone, available_from, available_to)
            VALUES (?, ?, ?, ?, ?)
            """,
            doctors,
        )
        conn.commit()
        logger.info("Doctors seeded successfully")
    except Exception:
        logger.exception("Failed to seed doctors")
    finally:
        if conn:
            conn.close()


def seed_availability():
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT COUNT(*) AS count FROM doctors")
        doctors_count = cur.fetchone()["count"]
        if doctors_count == 0:
            logger.warning("Skipping availability seed because doctors table is empty")
            return

        cur.execute("SELECT COUNT(*) AS count FROM doctor_availability")
        availability_count = cur.fetchone()["count"]
        if availability_count > 0:
            logger.info("Doctor availability already seeded")
            return

        schedules = {
            "Dr. Sarah Sharma": [("09:00", "12:00"), ("13:00", "17:00")],
            "Dr. Raj Patel": [("10:00", "13:00"), ("14:00", "16:00")],
            "Dr. Ananya Reddy": [("11:00", "14:00"), ("15:00", "18:00")],
            "Dr. Michael Chen": [("09:30", "12:30"), ("13:30", "15:30")],
            "Dr. Priya Nair": [("08:30", "11:30"), ("12:30", "14:30")],
        }

        start_day = datetime.now().date() + timedelta(days=1)
        records = []
        for day_offset in range(7):
            slot_date = (start_day + timedelta(days=day_offset)).strftime("%Y-%m-%d")
            for doctor_name, windows in schedules.items():
                for start_time, end_time in windows:
                    records.append((doctor_name, slot_date, start_time, end_time))

        cur.executemany(
            """
            INSERT INTO doctor_availability (doctor_name, available_date, start_time, end_time)
            VALUES (?, ?, ?, ?)
            """,
            records,
        )
        conn.commit()
        logger.info("Doctor availability seeded for next 7 days")
    except Exception:
        logger.exception("Failed to seed doctor availability")
    finally:
        if conn:
            conn.close()


def ensure_bootstrap():
    global _BOOTSTRAPPED
    if _BOOTSTRAPPED:
        return

    init_db()
    seed_doctors()
    seed_availability()
    _BOOTSTRAPPED = True
