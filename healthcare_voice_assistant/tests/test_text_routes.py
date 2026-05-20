import os

import pytest

from healthcare_voice_assistant.app import create_app


@pytest.fixture()
def client():
    os.environ.pop("REDIS_URL", None)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_language_prompt(client):
    response = client.post("/route_query", json={"query": ""})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["intent"] == "language_selection"


def test_basic_booking_flow(client):
    response = client.post("/route_query", json={"query": "English"})
    assert response.status_code == 200

    response = client.post(
        "/route_query",
        json={"query": "Book appointment with Dr. Sarah Sharma tomorrow at 10am, phone 1234567890"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["intent"] in {"appointment_booking", "fallback"}
