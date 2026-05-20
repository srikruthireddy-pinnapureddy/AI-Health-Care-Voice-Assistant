import os
import sys

from fastapi.testclient import TestClient

sys.path.append(os.path.abspath("."))
sys.path.append(os.path.abspath("voice_gateway"))

from voice_gateway.main import app


def test_health_endpoint():
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert "status" in payload
