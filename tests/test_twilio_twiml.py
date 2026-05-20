import os
import sys
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

sys.path.append(os.path.abspath("."))
sys.path.append(os.path.abspath("voice_gateway"))

import healthcare_voice_assistant.core.async_query_router as async_router
from voice_gateway.main import app


def test_incoming_call_twiml(monkeypatch):
    monkeypatch.setattr(async_router, "initialize_session", AsyncMock())
    client = TestClient(app)
    response = client.post(
        "/incoming-call",
        data={"CallSid": "CA123", "Language": "en"},
        headers={"X-Twilio-Signature": "test"},
    )
    assert response.status_code == 200
    assert "<Stream" in response.text
