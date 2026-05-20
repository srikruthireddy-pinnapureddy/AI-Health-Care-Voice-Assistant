import re
import logging

logger = logging.getLogger("clinic_voice_assistant.intent_classifier")

INTENT_GENERAL_INFO = "general_info"
INTENT_APPOINTMENT_BOOKING = "appointment_booking"
INTENT_FOLLOW_UP = "follow_up"
INTENT_EMERGENCY = "emergency"
INTENT_FALLBACK = "fallback"
INTENT_LANGUAGE_SELECTION = "language_selection"

GENERAL_INFO_KEYWORDS = {
    "timings": ["timing", "timings", "hours", "open", "closing", "working hours"],
    "location": ["location", "address", "where", "clinic located"],
    "services": ["service", "services", "department", "specialty", "specialities"],
    "reports": ["report", "reports", "lab report", "test report", "collect report"],
    "emergency": ["emergency", "urgent help", "emergency contact"],
    "phone": ["phone", "number", "contact", "call", "helpline"],
}

SPECIALTY_ALIASES = {
    "general physician": ["general physician", "general doctor", "general medicine", "gp", "physician"],
    "cardiologist": ["cardiologist", "cardiology", "heart doctor"],
    "dermatologist": ["dermatologist", "dermatology", "skin doctor"],
    "neurologist": ["neurologist", "neurology", "brain doctor"],
    "pediatrician": ["pediatrician", "pediatrics", "child doctor", "kids doctor"],
}


def normalize_text(text):
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def classify_intent(query_text):
    q = normalize_text(query_text)

    emergency_patterns = [
        "emergency",
        "urgent",
        "severe pain",
        "pain",
        "breathing",
        "accident",
        "911",
        "heart attack",
        "serious",
        "critical",
        "not breathing",
    ]
    if any(term in q for term in emergency_patterns):
        return INTENT_EMERGENCY

    follow_up_patterns = [
        "complaint",
        "call back",
        "callback",
        "issue unresolved",
        "unresolved",
        "follow up",
        "follow-up",
        "no response",
        "not resolved",
    ]
    if any(term in q for term in follow_up_patterns):
        return INTENT_FOLLOW_UP

    appointment_patterns = [
        "book appointment",
        "book",
        "schedule",
        "appointment",
        "visit",
        "physician",
        "specialist",
        "consult",
        "see",
    ]
    has_doctor_reference = bool(re.search(r"\bdr\.?\s+[a-zA-Z]", query_text, flags=re.IGNORECASE))
    has_time_reference = bool(re.search(r"\b\d{1,2}(:\d{2})?\s?(am|pm)\b", q))
    has_date_reference = "today" in q or "tomorrow" in q or bool(re.search(r"\d{4}-\d{2}-\d{2}", q))
    has_specialty_reference = any(alias in q for aliases in SPECIALTY_ALIASES.values() for alias in aliases)

    if any(term in q for term in appointment_patterns) or has_doctor_reference:
        if has_doctor_reference or has_time_reference or has_date_reference or has_specialty_reference:
            return INTENT_APPOINTMENT_BOOKING

    if any(term in q for term in appointment_patterns):
        return INTENT_APPOINTMENT_BOOKING

    specialty_keywords = {alias for aliases in SPECIALTY_ALIASES.values() for alias in aliases}
    if any(term in q for term in specialty_keywords):
        return INTENT_APPOINTMENT_BOOKING

    flat_general_keywords = {word for words in GENERAL_INFO_KEYWORDS.values() for word in words}
    if any(term in q for term in flat_general_keywords):
        return INTENT_GENERAL_INFO

    return INTENT_FALLBACK


def infer_info_key(query_text):
    q = normalize_text(query_text)
    for key, words in GENERAL_INFO_KEYWORDS.items():
        if any(word in q for word in words):
            return key
    return "services"
