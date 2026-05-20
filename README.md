# Multilingual Healthcare Voice Assistant

This project refactors the existing Flask receptionist backend into a modular, voice-enabled assistant with Faster-Whisper STT, OmniVoice TTS, Redis-backed sessions, and a React browser MVP.

## Quick Start

1. Create a virtual environment and install dependencies:

```bash
pip install -r requirements.txt
```

2. Start Redis (required for session memory):

```bash
docker run -p 6379:6379 redis:7-alpine
```

3. Run the backend:

```bash
python app.py
```

4. Run the FastAPI voice gateway:

```bash
cd voice_gateway
uvicorn main:app --host 0.0.0.0 --port 8001
```

4. Open the frontend:

- Open [healthcare_voice_assistant/frontend/index.html](healthcare_voice_assistant/frontend/index.html) in a browser.

## Environment Variables

- `REDIS_URL`: Redis connection string (default: `redis://localhost:6379/0`)
- `MAX_CONTENT_LENGTH`: Max request size in bytes (default: 20 MB)
- `OMNIVOICE_SPEAKER`: Fixed speaker name for TTS
- `VOICE_GATEWAY_TWILIO_WS_URL`: Public wss endpoint for Twilio Media Streams
- `SESSION_TTL_ACTIVE_SECONDS`: Active call session TTL (seconds)
- `SESSION_TTL_POST_CALL_SECONDS`: Post-call retention TTL (seconds)

## API Endpoints

- `POST /route_query`
- `POST /voice_query`
- `POST /save_booking`
- `POST /cancel_booking`
- `POST /reschedule_booking`
- `POST /get_doctors_by_specialty`
- `POST /check_slot`
- `POST /get_or_create_patient`
- `POST /save_query_result`
- `GET /analytics/summary`
- `GET /analytics/export`

## Docker

```bash
docker compose up --build
```

The Nginx reverse proxy exposes:

- Backend: http://localhost:8080/
- Voice gateway: http://localhost:8080/incoming-call
- Websocket: ws://localhost:8080/media-stream

## Tests

```bash
pytest -q
```
