from flask import Blueprint, jsonify, request

from ..database.analytics import get_analytics_summary_payload, export_appointments_to_excel
from ..database.db import ensure_bootstrap

analytics_routes = Blueprint("analytics_routes", __name__)


@analytics_routes.route("/analytics/summary", methods=["GET"])
def api_analytics_summary():
    ensure_bootstrap()
    payload = get_analytics_summary_payload()
    return jsonify({"success": True, **payload}), 200


@analytics_routes.route("/analytics/export", methods=["GET"])
def api_analytics_export():
    ensure_bootstrap()
    file_name = request.args.get("file", "appointments_data.xlsx")
    export_result = export_appointments_to_excel(file_name=file_name)
    status_code = 200 if export_result.get("success") else 500
    return jsonify(export_result), status_code
