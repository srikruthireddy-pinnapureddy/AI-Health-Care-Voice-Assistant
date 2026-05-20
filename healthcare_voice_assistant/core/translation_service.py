import logging
import re

try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

logger = logging.getLogger("clinic_voice_assistant.translation_service")

LANG_EN = "en"
LANG_TA = "ta"
LANG_ML = "ml"
SUPPORTED_LANGUAGES = {LANG_EN, LANG_TA, LANG_ML}

LANGUAGE_PROMPT = "Which language are you comfortable with? English, Tamil, or Malayalam?"
LANGUAGE_OPTIONS = ["English", "Tamil", "Malayalam"]
LANGUAGE_CONFIRMATION = {
    LANG_EN: "Great, I will assist you in English.",
    LANG_TA: "நான் தமிழில் உங்களுக்கு உதவுகிறேன்.",
    LANG_ML: "ഞാൻ മലയാളത്തിൽ നിങ്ങളെ സഹായിക്കും.",
}
LANGUAGE_RETRY = "I did not understand the language choice. Please choose English, Tamil, or Malayalam."


def normalize_text(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def detect_language_choice(query_text):
    q = normalize_text(query_text)
    compact_q = q.replace(" ", "")

    mapping = {
        LANG_EN: {"english", "en", "inglish", "eng"},
        LANG_TA: {"tamil", "ta", "தமிழ்", "தமிழ", "thamizh", "tamizh"},
        LANG_ML: {"malayalam", "ml", "മലയാളം", "malayalum", "malayalm"},
    }

    for lang_code, aliases in mapping.items():
        for alias in aliases:
            alias_norm = normalize_text(alias)
            if q == alias_norm or compact_q == alias_norm.replace(" ", ""):
                return lang_code
            if re.search(rf"\b{re.escape(alias_norm)}\b", q):
                return lang_code
    return None


def translate_to_english(text, source_lang):
    if not text:
        return text
    if source_lang == LANG_EN:
        return text

    if GoogleTranslator is None:
        logger.warning("Translation library unavailable; using original text as English")
        return text

    try:
        translated = GoogleTranslator(source=source_lang, target=LANG_EN).translate(text)
        return translated or text
    except Exception:
        logger.exception("Failed translating input to English; falling back to original text")
        return text


def translate_from_english(text, target_lang):
    if not text:
        return text
    if target_lang == LANG_EN:
        return text

    if GoogleTranslator is None:
        logger.warning("Translation library unavailable; returning English response")
        return text

    try:
        translated = GoogleTranslator(source=LANG_EN, target=target_lang).translate(text)
        return translated or text
    except Exception:
        logger.exception("Failed translating response from English; falling back to English")
        return text
