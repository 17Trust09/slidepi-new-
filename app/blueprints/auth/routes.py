from flask import Blueprint, render_template, request, redirect, url_for, session, flash
from passlib.hash import bcrypt
from functools import wraps
from time import time
from app.db import get_session
from app.models.user import User, VALID_ROLES

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")

# --- simpel: In-Memory Versuchszähler (pro Prozess) ---
_ATTEMPTS: dict[tuple[str, str], list[float]] = {}
MAX_ATTEMPTS = 5         # max. 5 Versuche ...
WINDOW_SECONDS = 10 * 60 # ... pro 10 Minuten

def _client_ip() -> str:
    # hinter Proxy: X-Forwarded-For berücksichtigen (einfachste Variante)
    fwd = request.headers.get("X-Forwarded-For")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or "unknown"

def _is_locked(ip: str, username: str) -> bool:
    key = (ip, username.lower())
    now = time()
    attempts = _ATTEMPTS.get(key, [])
    # alte Einträge entfernen
    attempts = [t for t in attempts if now - t <= WINDOW_SECONDS]
    _ATTEMPTS[key] = attempts
    return len(attempts) >= MAX_ATTEMPTS

def _register_fail(ip: str, username: str) -> None:
    key = (ip, username.lower())
    _ATTEMPTS.setdefault(key, []).append(time())

def _clear_attempts(ip: str, username: str) -> None:
    _ATTEMPTS.pop((ip, username.lower()), None)

# === Helferfunktionen ===
def _ensure_admin():
    """Erstellt einen Default-Admin falls keiner existiert"""
    db = get_session()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(username="admin", password_hash=bcrypt.hash("raspberry"), role="admin")
            db.add(admin)
            db.commit()
    finally:
        db.close()

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user"):
            flash("Bitte einloggen.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated

def role_required(allowed_roles: tuple[str, ...]):
    """Erlaubt Zugriff nur für bestimmte Rollen."""
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            u = session.get("user")
            if not u:
                flash("Bitte einloggen.", "error")
                return redirect(url_for("auth.login"))
            if u.get("role") not in allowed_roles:
                flash("Keine Berechtigung für diesen Bereich.", "error")
                return redirect(url_for("core.index"))
            return f(*args, **kwargs)
        return decorated
    return wrapper

def admin_required(f):
    """Nur Admins."""
    return role_required(("admin",))(f)

# === Login / Logout ===
@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    _ensure_admin()
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        ip = _client_ip()

        if _is_locked(ip, username):
            flash("Zu viele Fehlversuche. Bitte später erneut versuchen.", "error")
            return render_template("login.html")

        db = get_session()
        try:
            user = db.query(User).filter(User.username == username).first()
            if user and bcrypt.verify(password, user.password_hash):
                session.permanent = True  # nutzt PERMANENT_SESSION_LIFETIME
                session["user"] = {"id": user.id, "username": user.username, "role": user.role}
                _clear_attempts(ip, username)
                flash("Erfolgreich eingeloggt.", "success")
                return redirect(url_for("core.index"))
            else:
                _register_fail(ip, username)
                remaining = max(0, MAX_ATTEMPTS - len(_ATTEMPTS.get((ip, username.lower()), [])))
                msg = "Ungültige Anmeldedaten."
                if remaining <= 2:
                    msg += f" ({remaining} Versuch(e) übrig)"
                flash(msg, "error")
        finally:
            db.close()
    return render_template("login.html")

@auth_bp.route("/logout")
def logout():
    session.clear()
    flash("Abgemeldet.", "info")
    return redirect(url_for("auth.login"))

# === Passwort ändern (alle Rollen) ===
@auth_bp.route("/me/password", methods=["GET", "POST"])
@login_required
def change_password():
    if request.method == "POST":
        current_pw = request.form.get("current_password", "")
        new_pw = request.form.get("new_password", "")
        new_pw2 = request.form.get("new_password2", "")

        if not new_pw or len(new_pw) < 6:
            flash("Neues Passwort muss mindestens 6 Zeichen lang sein.", "error")
            return render_template("change_password.html")

        if new_pw != new_pw2:
            flash("Neue Passwörter stimmen nicht überein.", "error")
            return render_template("change_password.html")

        db = get_session()
        try:
            u = db.get(User, session["user"]["id"])
            if not u or not bcrypt.verify(current_pw, u.password_hash):
                flash("Aktuelles Passwort ist falsch.", "error")
                return render_template("change_password.html")

            u.password_hash = bcrypt.hash(new_pw)
            db.commit()
            flash("Passwort aktualisiert.", "success")
            return redirect(url_for("core.index"))
        finally:
            db.close()

    return render_template("change_password.html")

# === Admin-UI für Benutzerverwaltung (inkl. Rollen ändern) ===
@auth_bp.route("/users", methods=["GET", "POST"])
@admin_required
def manage_users():
    db = get_session()
    try:
        if request.method == "POST":
            action = request.form.get("action")

            if action == "create":
                name = request.form.get("username", "").strip()
                pw = request.form.get("password", "")
                role = request.form.get("role", "user").lower().strip()
                if role not in VALID_ROLES:
                    flash("Ungültige Rolle.", "error")
                elif not name or not pw:
                    flash("Benutzername und Passwort erforderlich.", "error")
                elif db.query(User).filter(User.username == name).first():
                    flash("Benutzer existiert bereits.", "error")
                else:
                    u = User(username=name, password_hash=bcrypt.hash(pw), role=role)
                    db.add(u)
                    db.commit()
                    flash("Benutzer erstellt.", "success")

            elif action == "delete":
                uid = int(request.form.get("user_id"))
                u = db.get(User, uid)
                if not u:
                    flash("Benutzer nicht gefunden.", "error")
                elif u.username == "admin":
                    flash("Der Standard-Admin kann nicht gelöscht werden.", "error")
                elif uid == session["user"]["id"]:
                    flash("Eigenes Konto kann nicht gelöscht werden.", "error")
                else:
                    db.delete(u)
                    db.commit()
                    flash("Benutzer gelöscht.", "success")

            elif action == "update_role":
                uid = int(request.form.get("user_id"))
                new_role = request.form.get("role", "user").lower().strip()
                if new_role not in VALID_ROLES:
                    flash("Ungültige Rolle.", "error")
                else:
                    u = db.get(User, uid)
                    if not u:
                        flash("Benutzer nicht gefunden.", "error")
                    elif u.username == "admin":
                        flash("Die Rolle des Standard-Admins kann nicht geändert werden.", "error")
                    else:
                        u.role = new_role
                        db.commit()
                        flash("Rolle aktualisiert.", "success")

        users = db.query(User).all()
        return render_template("manage_users.html", users=users, VALID_ROLES=VALID_ROLES)
    finally:
        db.close()
