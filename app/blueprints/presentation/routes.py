from flask import Blueprint, render_template

presentation_bp = Blueprint("presentation", __name__)

@presentation_bp.route("/")
def player():
    # Standard-Player mit Overlay/Controls
    return render_template("play.html")

@presentation_bp.route("/kiosk")
def player_kiosk():
    # Reiner Kiosk-Player ohne Overlay/Controls
    return render_template("play_kiosk.html")
