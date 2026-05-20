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


def test_analytics_summary(client):
    response = client.get("/analytics/summary")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
