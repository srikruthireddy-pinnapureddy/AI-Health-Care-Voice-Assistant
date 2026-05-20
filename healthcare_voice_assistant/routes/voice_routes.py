import logging
import os
import uuid

from flask import Blueprint, jsonify, request, send_from_directory
from werkzeug.utils import secure_filename

from ..core.query_router import process_query
from ..core.translation_service import (
    LANG_EN,
    SUPPORTED_LANGUAGES,
    translate_from_english,
    translate_to_english,
)
from ..database.db import ensure_bootstrap
from ..core.session_store import get_session_context, save_session_context
from ..speech.audio_utils import normalize_audio
from ..speech.whisper_engine import transcribe_audio
from ..speech.vad_engine import detect_speech, trim_silence
from ..tts.omnivoice_engine import generate_speech

voice_routes = Blueprint("voice_routes", __name__)
logger = logging.getLogger("clinic_voice_assistant.voice_routes")

ALLOWED_AUDIO_EXTENSIONS = {"wav", "mp3", "m4a", "ogg", "webm"}
MAX_AUDIO_MB = 15

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMP_AUDIO_DIR = os.path.join(BASE_DIR, "speech", "temp_audio")
NORMALIZED_AUDIO_DIR = os.path.join(BASE_DIR, "speech", "temp_audio")
TTS_AUDIO_DIR = os.path.join(BASE_DIR, "tts", "generated_audio")


def _allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_AUDIO_EXTENSIONS


def _get_session_id():
    return (
        request.form.get("session_id")
        or request.form.get("sessionId")
        or request.args.get("session_id")
        or request.args.get("sessionId")
        or request.headers.get("X-Session-Id")
        or str(uuid.uuid4())
    )


@voice_routes.route("/audio/<path:filename>", methods=["GET"])
def get_audio_file(filename):
    return send_from_directory(TTS_AUDIO_DIR, filename, as_attachment=False)


@voice_routes.route("/voice_query", methods=["POST"])
def voice_query():
    ensure_bootstrap()

    if request.content_length and request.content_length > MAX_AUDIO_MB * 1024 * 1024:
        return jsonify({"error": "Audio file too large"}), 413

    if "audio" not in request.files:
        return jsonify({"error": "Missing audio file"}), 400

    file = request.files["audio"]
    if file.filename == "":
        return jsonify({"error": "Empty filename"}), 400

    if not _allowed_file(file.filename):
        return jsonify({"error": "Unsupported audio format"}), 400

    os.makedirs(TEMP_AUDIO_DIR, exist_ok=True)
    os.makedirs(TTS_AUDIO_DIR, exist_ok=True)

    session_id = _get_session_id()
    session_context = get_session_context(session_id)

    raw_name = secure_filename(file.filename)
    temp_input_path = os.path.join(TEMP_AUDIO_DIR, f"{uuid.uuid4().hex}_{raw_name}")
    normalized_path = os.path.join(NORMALIZED_AUDIO_DIR, f"normalized_{uuid.uuid4().hex}.wav")
    trimmed_path = os.path.join(NORMALIZED_AUDIO_DIR, f"trimmed_{uuid.uuid4().hex}.wav")

    try:
        file.save(temp_input_path)
        normalize_audio(temp_input_path, normalized_path)

        if detect_speech(normalized_path):
            trimmed_path, _ = trim_silence(normalized_path, trimmed_path)
        else:
            trimmed_path = normalized_path

        stt_result = transcribe_audio(trimmed_path)
        transcript = stt_result.get("text", "")
        detected_language = stt_result.get("language", LANG_EN)

        selected_language = session_context.get("language")
        if not selected_language:
            if detected_language in SUPPORTED_LANGUAGES:
                selected_language = detected_language
            else:
                selected_language = LANG_EN
            session_context["language"] = selected_language

        query_in_english = translate_to_english(transcript, selected_language)
        result, session_context = process_query(query_in_english, session_context)
        response_in_english = result.get("response", "")
        localized_response = translate_from_english(response_in_english, selected_language)

        audio_path = generate_speech(localized_response, output_dir=TTS_AUDIO_DIR)
        audio_url = f"/audio/{os.path.basename(audio_path)}"

        save_session_context(session_id, session_context)

        return jsonify(
            {
                "transcript": transcript,
                "language": selected_language,
                "response_text": localized_response,
                "audio_url": audio_url,
            }
        ), 200

    except Exception:
        logger.exception("Failed to process voice query")
        return jsonify({"error": "Unable to process voice query"}), 500

    finally:
        for path in (temp_input_path, normalized_path, trimmed_path):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                logger.warning("Failed to delete temp file: %s", path)
