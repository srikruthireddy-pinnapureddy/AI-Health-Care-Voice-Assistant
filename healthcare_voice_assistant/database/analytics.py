import logging
import os

from .db import get_db, BASE_DIR, APPOINTMENTS_MIGRATION_STEPS

logger = logging.getLogger("clinic_voice_assistant.analytics")


def get_analytics_queries():
    date_expr = "COALESCE(NULLIF(TRIM(date), ''), appointment_date)"
    time_expr = "COALESCE(NULLIF(TRIM(time), ''), appointment_time)"

    return {
        "total_appointments_per_day": f"""
            SELECT {date_expr} AS appointment_day,
                   COUNT(*) AS total_bookings
            FROM appointments
            WHERE LOWER(status) = 'booked'
            GROUP BY {date_expr}
            ORDER BY appointment_day
        """,
        "peak_booking_hours": f"""
            SELECT SUBSTR({time_expr}, 1, 2) || ':00' AS hour_slot,
                   COUNT(*) AS booking_count
            FROM appointments
            WHERE LOWER(status) = 'booked'
            GROUP BY SUBSTR({time_expr}, 1, 2)
            ORDER BY booking_count DESC, hour_slot
        """,
        "most_popular_doctor": """
            SELECT doctor_name,
                   COUNT(*) AS total_bookings
            FROM appointments
            WHERE LOWER(status) = 'booked'
            GROUP BY doctor_name
            ORDER BY total_bookings DESC, doctor_name
        """,
        "cancellation_rate": """
            SELECT COUNT(*) AS total_appointments,
                   SUM(CASE WHEN LOWER(status) = 'cancelled' THEN 1 ELSE 0 END) AS total_cancelled,
                   ROUND(
                       100.0 * SUM(CASE WHEN LOWER(status) = 'cancelled' THEN 1 ELSE 0 END)
                       / NULLIF(COUNT(*), 0),
                       2
                   ) AS cancellation_rate
            FROM appointments
        """,
        "weekly_trends": f"""
            SELECT STRFTIME('%Y-W%W', {date_expr}) AS year_week,
                   COUNT(*) AS total_bookings
            FROM appointments
            WHERE LOWER(status) = 'booked'
            GROUP BY STRFTIME('%Y-W%W', {date_expr})
            ORDER BY year_week
        """,
        "full_dataset": f"""
            SELECT id,
                   patient_name,
                   doctor_name,
                   {date_expr} AS date,
                   {time_expr} AS time,
                   LOWER(status) AS status,
                   created_at
            FROM appointments
            ORDER BY date, time, doctor_name
        """,
    }


def run_analytics_query(query):
    conn = None
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute(query)
        rows = cur.fetchall()
        return [dict(row) for row in rows]
    except Exception:
        logger.exception("Failed to run analytics query")
        return []
    finally:
        if conn:
            conn.close()


def get_analytics_summary_payload():
    queries = get_analytics_queries()

    total_rows = run_analytics_query(
        "SELECT COUNT(*) AS total_bookings FROM appointments WHERE LOWER(status) = 'booked'"
    )
    top_doctor_rows = run_analytics_query(queries["most_popular_doctor"])
    peak_time_rows = run_analytics_query(queries["peak_booking_hours"])
    cancellation_rows = run_analytics_query(queries["cancellation_rate"])

    return {
        "total_bookings": int(total_rows[0]["total_bookings"]) if total_rows else 0,
        "top_doctor": top_doctor_rows[0]["doctor_name"] if top_doctor_rows else None,
        "peak_time": peak_time_rows[0]["hour_slot"] if peak_time_rows else None,
        "cancellation_rate": float(cancellation_rows[0]["cancellation_rate"] or 0.0) if cancellation_rows else 0.0,
        "migration_steps": APPOINTMENTS_MIGRATION_STEPS,
    }


def export_appointments_to_excel(file_name="appointments_data.xlsx"):
    try:
        import pandas as pd
    except Exception:
        return {
            "success": False,
            "message": "pandas/openpyxl is required. Install: pip install pandas openpyxl",
        }

    conn = None
    try:
        queries = get_analytics_queries()
        conn = get_db()

        full_df = pd.read_sql_query(queries["full_dataset"], conn)
        per_day_df = pd.read_sql_query(queries["total_appointments_per_day"], conn)
        peak_hours_df = pd.read_sql_query(queries["peak_booking_hours"], conn)
        popular_doctor_df = pd.read_sql_query(queries["most_popular_doctor"], conn)
        cancellation_df = pd.read_sql_query(queries["cancellation_rate"], conn)
        weekly_df = pd.read_sql_query(queries["weekly_trends"], conn)

        output_path = os.path.join(BASE_DIR, file_name)
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            full_df.to_excel(writer, sheet_name="appointments", index=False)
            per_day_df.to_excel(writer, sheet_name="bookings_per_day", index=False)
            peak_hours_df.to_excel(writer, sheet_name="peak_hours", index=False)
            popular_doctor_df.to_excel(writer, sheet_name="doctor_popularity", index=False)
            cancellation_df.to_excel(writer, sheet_name="cancellation_rate", index=False)
            weekly_df.to_excel(writer, sheet_name="weekly_trends", index=False)

        return {
            "success": True,
            "file": output_path,
            "records": len(full_df.index),
        }
    except Exception:
        logger.exception("Failed to export appointments to Excel")
        return {
            "success": False,
            "message": "Failed to export appointments to Excel",
        }
    finally:
        if conn:
            conn.close()
