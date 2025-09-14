import os
from datetime import timedelta
from flask import Flask
from dotenv import load_dotenv

from app.db import init_db
from app.blueprints.core.routes import core_bp
from app.blueprints.auth.routes import auth_bp
from app.blueprints.media.routes import media_bp
from app.blueprints.presentation.routes import presentation_bp
from app.blueprints.api.routes import api_bp
from app.blueprints.admin.routes import admin_bp

def create_app() -> Flask:
    load_dotenv()
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Secrets / DB
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "slidepi.db"))
    app.config["DATABASE_URL"] = os.getenv("DATABASE_URL", f"sqlite:///{db_path}")

    # Sicherere Session-Cookies
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )

    # === Upload-Settings ===
    # Max. Größe pro Request (standard: 200 MB) – kann via .env überschrieben werden
    max_mb = int(os.getenv("UPLOAD_MAX_MB", "200"))
    app.config["MAX_CONTENT_LENGTH"] = max_mb * 1024 * 1024
    # Erlaubte MIME-Präfixe (nur Bilder/Videos)
    app.config["ALLOWED_MIME_PREFIXES"] = ("image/", "video/")

    init_db(app.config["DATABASE_URL"])

    # Blueprints
    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(media_bp, url_prefix="/media")
    app.register_blueprint(presentation_bp, url_prefix="/present")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    app.jinja_env.globals.update(APP_NAME="SlidePi")
    return app
