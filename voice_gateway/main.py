import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from config import settings
from observability_routes import router as observability_router
from twilio_handler import router as twilio_router
from websocket_server import router as websocket_router


def _configure_logging() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


_configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name)


@app.get("/health")
async def health() -> dict:
    from monitoring.health_checks import get_health

    return await get_health()


@app.exception_handler(Exception)
async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    logger.exception("Unhandled error", extra={"path": request.url.path})
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


app.include_router(twilio_router)
app.include_router(websocket_router)
app.include_router(observability_router)
