import os
import sys

from fastapi.testclient import TestClient

sys.path.append(os.path.abspath("."))
sys.path.append(os.path.abspath("voice_gateway"))

from voice_gateway.main import app


def test_metrics_endpoint():
    client = TestClient(app)
    response = client.get("/metrics")
    assert response.status_code == 200
    payload = response.json()
    assert "counters" in payload
    assert "latencies" in payload
