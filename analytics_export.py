from healthcare_voice_assistant.database.db import ensure_bootstrap
from healthcare_voice_assistant.database.analytics import export_appointments_to_excel


if __name__ == "__main__":
    ensure_bootstrap()
    result = export_appointments_to_excel("appointments_data.xlsx")
    print(result)
