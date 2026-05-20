from flask import Flask, request, jsonify
import sqlite3
from datetime import datetime, timedelta
import os
import re
from healthcare_voice_assistant.app import create_app

app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)

