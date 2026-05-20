import logging
from xml.etree.ElementTree import Element, SubElement, tostring

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response

from config import settings
from healthcare_voice_assistant.core.async_query_router import initialize_session

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/incoming-call")
async def incoming_call(
    request: Request,
    x_twilio_signature: str | None = Header(default=None),
) -> Response:
    form = await request.form()
    call_sid = form.get("CallSid")
    language = form.get("Language") or "en"

    if not call_sid:
        raise HTTPException(status_code=400, detail="Missing CallSid")

    if not x_twilio_signature:
        logger.warning("Missing X-Twilio-Signature header")

    await initialize_session(
        session_id=call_sid,
        metadata={
            "call_sid": call_sid,
            "language": language,
            "current_state": "incoming_call",
        },
    )

    response_xml = _build_twiml(settings.twilio_ws_url)
    return Response(content=response_xml, media_type="application/xml")


def _build_twiml(ws_url: str) -> str:
    response = Element("Response")
    connect = SubElement(response, "Connect")
    stream = SubElement(connect, "Stream")
    stream.set("url", ws_url)
    return tostring(response, encoding="unicode")
