import logging
import os

from flask import Flask
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from .core.session_store import init_session_store
from .routes.text_routes import text_routes
from .routes.voice_routes import voice_routes
from .routes.analytics_routes import analytics_routes
from .database.db import ensure_bootstrap

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("clinic_voice_assistant")


def create_app():
    app = Flask(__name__, static_folder="static", static_url_path="/static")
    app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", str(20 * 1024 * 1024)))

    CORS(app)

    storage_uri = os.getenv("REDIS_URL", "memory://")
    Limiter(
        get_remote_address,
        app=app,
        default_limits=["200 per day", "60 per minute"],
        storage_uri=storage_uri,
    )

    init_session_store(app)
    ensure_bootstrap()

    app.register_blueprint(text_routes)
    app.register_blueprint(voice_routes)
    app.register_blueprint(analytics_routes)
    return app


app = create_app()


if __name__ == "__main__":
    run_port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=run_port, debug=True)
