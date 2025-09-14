import os
from datetime import timedelta
from flask import Flask, redirect, render_template_string
from dotenv import load_dotenv

from app.db import init_db

# Blueprints (deine bestehenden)
from app.blueprints.core.routes import core_bp
from app.blueprints.auth.routes import auth_bp
from app.blueprints.media.routes import media_bp
from app.blueprints.presentation.routes import presentation_bp
from app.blueprints.api.routes import api_bp
from app.blueprints.admin.routes import admin_bp  # ok, auch wenn /admin -> Dashboard leitet

# Meta-Blueprint (Healthcheck)
from app.blueprints.meta.routes import meta_bp

# Settings
from app.services.settings_service import ensure_default_settings, get_settings_dict

# Rollen-Helpers
from app.services.roles import get_current_role, has_role, can


def create_app() -> Flask:
    load_dotenv()
    app = Flask(__name__, template_folder="templates", static_folder="static")

    # Secrets / DB
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-change-me")
    db_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "slidepi.db"))
    app.config["DATABASE_URL"] = os.getenv("DATABASE_URL", f"sqlite:///{db_path}")

    # Sessions härten
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )

    # Upload-Limits
    max_mb = int(os.getenv("UPLOAD_MAX_MB", "200"))
    app.config["MAX_CONTENT_LENGTH"] = max_mb * 1024 * 1024
    app.config["ALLOWED_MIME_PREFIXES"] = ("image/", "video/")

    # DB initialisieren
    init_db()

    # Standard-Settings sicherstellen (idempotent)
    ensure_default_settings()

    # Blueprints registrieren
    app.register_blueprint(meta_bp)                          # /health
    app.register_blueprint(core_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(media_bp, url_prefix="/media")
    app.register_blueprint(presentation_bp, url_prefix="/present")
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(admin_bp, url_prefix="/admin")

    # OPTIONAL: Admin-Network (wird registriert, falls vorhanden)
    try:
        from app.routes.admin_network import bp as admin_network_bp
        app.register_blueprint(admin_network_bp, url_prefix="/admin/network")
    except Exception:
        # Route ist (noch) nicht vorhanden; App bleibt lauffähig in PyCharm
        pass

    # Settings + Rollen für Templates bereitstellen
    @app.context_processor
    def inject_settings_and_roles():
        s = get_settings_dict()
        return {
            "APP_NAME": s.get("app_name", "SlidePi"),
            "SETTINGS": s,
            "CURRENT_ROLE": get_current_role(),
            "has_role": has_role,
            "can": can,
        }

    # Root
    @app.get("/")
    def index():
        return (
            "<html><body style='font-family:system-ui;background:#0b0f14;color:#eaeff7'>"
            "<h1>SlidePi</h1>"
            "<p>OK – sieh dir das <a href='/'>Dashboard</a> an oder nutze <a href='/health'>/health</a> für einen Schnellcheck.</p>"
            "</body></html>"
        )

    # /admin -> Dashboard (du nutzt kein separates Admin-Panel)
    @app.get("/admin")
    def admin_redirect():
        return redirect("/")

    # 403-Seite
    @app.errorhandler(403)
    def forbidden(_e):
        return render_template_string(
            "<html><body style='font-family:system-ui;background:#0b0f14;color:#eaeff7'>"
            "<h1>403 – Zugriff verweigert</h1>"
            "<p>Dir fehlen die nötigen Rechte für diese Aktion.</p>"
            "</body></html>"
        ), 403

    return app
