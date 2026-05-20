import os
from io import BytesIO

import pytest

from healthcare_voice_assistant.app import create_app


@pytest.fixture()
def client():
    os.environ.pop("REDIS_URL", None)
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_voice_route_missing_file(client):
    response = client.post("/voice_query")
    assert response.status_code == 400


def test_voice_route_invalid_file(client):
    data = {"audio": (BytesIO(b"bad"), "bad.txt")}
    response = client.post("/voice_query", data=data, content_type="multipart/form-data")
    assert response.status_code == 400
