from flask import Blueprint, render_template, redirect, url_for, session

core_bp = Blueprint("core", __name__)

@core_bp.route("/")
def index():
    if not session.get("user"):
        return redirect(url_for("auth.login"))
    return render_template("dashboard.html")
