# app/blueprints/admin/routes.py
import os
import subprocess
import shlex
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app

from app.db import get_session
from app.services.playlist_service import (
    list_playlists, create_playlist, delete_playlist,
    set_active_playlist, get_playlist_items, replace_playlist_items,
    get_or_create_default_playlist,
)
from app.services.media_service import list_media
from app.blueprints.auth.routes import role_required, admin_required
from app.services.settings_service import set_setting, get_settings_dict, ensure_default_settings

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# === Playlists (Admin & Editor) ===
@admin_bp.route("/playlists", methods=["GET", "POST"])
@role_required(("admin", "editor"))
def playlists_page():
    db = get_session()
    try:
        # sicherstellen, dass es eine Default-Playlist gibt
        get_or_create_default_playlist(db)

        if request.method == "POST":
            action = (request.form.get("action") or "").strip()

            if action == "create":
                name = (request.form.get("name") or "").strip()
                if not name:
                    flash("Name darf nicht leer sein.", "error")
                else:
                    new_pl = create_playlist(db, name)
                    flash("Playlist erstellt.", "success")
                    # direkt in den Bearbeiten-Screen dieser Playlist
                    return redirect(url_for("admin.playlists_page", id=new_pl.id))

            elif action == "delete":
                pid_raw = request.form.get("playlist_id")
                if not pid_raw or not pid_raw.isdigit():
                    flash("Ungültige Playlist-ID.", "error")
                else:
                    pid = int(pid_raw)
                    if delete_playlist(db, pid):
                        flash("Playlist gelöscht.", "success")
                    else:
                        flash("Playlist nicht gefunden.", "error")
                    return redirect(url_for("admin.playlists_page"))

            elif action == "activate":
                pid_raw = request.form.get("playlist_id")
                if not pid_raw or not pid_raw.isdigit():
                    flash("Ungültige Playlist-ID.", "error")
                else:
                    pid = int(pid_raw)
                    if set_active_playlist(db, pid):
                        flash("Aktive Playlist geändert.", "success")
                        return redirect(url_for("admin.playlists_page", id=pid))
                    else:
                        flash("Playlist nicht gefunden.", "error")

            elif action == "save_items":
                pid_raw = request.form.get("playlist_id")
                if not pid_raw or not pid_raw.isdigit():
                    flash("Ungültige Playlist-ID.", "error")
                else:
                    pid = int(pid_raw)
                    order_csv = request.form.get("media_order", "")
                    dur_csv = request.form.get("durations", "")

                    media_ids = [int(x) for x in order_csv.split(",") if x.strip().isdigit()]
                    durations = (
                        [int(x) if x.strip().isdigit() else None for x in dur_csv.split(",")]
                        if dur_csv else None
                    )

                    replace_playlist_items(db, pid, media_ids, durations)
                    flash("Playlist-Inhalte gespeichert.", "success")
                    return redirect(url_for("admin.playlists_page", id=pid))

            # Fallback nach POST
            return redirect(url_for("admin.playlists_page"))

        # --- GET ---
        playlists = list_playlists(db)

        # gewählte Playlist-ID bestimmen: query?id=... oder aktive Playlist
        selected_id = None
        qid = request.args.get("id")
        if qid and qid.isdigit():
            selected_id = int(qid)
        else:
            for p in playlists:
                if getattr(p, "is_active", False):
                    selected_id = p.id
                    break

        # Items & Medien laden
        items = get_playlist_items(db, selected_id) if selected_id is not None else []
        media = list_media(db)

        return render_template(
            "admin_playlists.html",
            playlists=playlists,
            selected_id=selected_id,
            items=items,
            media=media,
        )
    finally:
        db.close()


# === Settings (nur Admin) ===
@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings_page():
    if request.method == "POST":
        app_name = (request.form.get("app_name") or "").strip()
        theme = (request.form.get("theme") or "dark").strip().lower()
        default_duration = (request.form.get("default_duration") or "10").strip()

        if not app_name:
            flash("App-Name darf nicht leer sein.", "error")
            return redirect(url_for("admin.settings_page"))

        if theme not in ("dark", "light", "auto"):
            flash("Ungültiges Theme.", "error")
            return redirect(url_for("admin.settings_page"))

        try:
            val = int(default_duration)
            if val < 1 or val > 3600:
                raise ValueError()
        except ValueError:
            flash("Standard-Dauer muss zwischen 1 und 3600 Sekunden liegen.", "error")
            return redirect(url_for("admin.settings_page"))

        # Speichern
        set_setting("app_name", app_name)
        set_setting("theme", theme)
        set_setting("default_duration", str(val))

        # Logo-Upload (optional)
        logo = request.files.get("logo")
        if logo and logo.filename:
            if not (logo.mimetype or "").startswith("image/"):
                flash("Logo muss ein Bild sein.", "error")
                return redirect(url_for("admin.settings_page"))
            static_img_dir = os.path.join(current_app.static_folder, "img")
            os.makedirs(static_img_dir, exist_ok=True)
            logo_path = os.path.join(static_img_dir, "logo.png")
            try:
                logo.save(logo_path)
            except Exception as ex:  # pragma: no cover
                flash(f"Logo-Upload fehlgeschlagen: {ex}", "error")
                return redirect(url_for("admin.settings_page"))

        flash("Einstellungen gespeichert.", "success")
        return redirect(url_for("admin.settings_page"))

    # GET
    s = get_settings_dict()
    return render_template("admin_settings.html", s=s)


# === System-Aktionen (nur Admin) ===
@admin_bp.post("/system/actions")
@admin_required
def system_actions():
    """
    Einzelaktionen im System-Tab:
    - create_defaults: ensure_default_settings()
    - ensure_default_playlist: get_or_create_default_playlist()
    - git_update: git pull im Projektverzeichnis, falls .git vorhanden
    - set_login_timeout: Setting 'login_timeout_minutes' setzen (als Zahl)
    """
    action = (request.form.get("action") or "").strip()

    # 1) Default-Einstellungen
    if action == "create_defaults":
        try:
            ensure_default_settings()
            flash("Default-Einstellungen angelegt/aktualisiert.", "success")
        except Exception as ex:
            flash(f"Fehler bei Default-Einstellungen: {ex}", "error")

    # 2) Default-Playlist
    elif action == "ensure_default_playlist":
        db = get_session()
        try:
            pl = get_or_create_default_playlist(db)
            flash(f"Playlist vorhanden: '{pl.name}' (ID {pl.id}).", "success")
        except Exception as ex:
            flash(f"Fehler beim Sicherstellen der Playlist: {ex}", "error")
        finally:
            db.close()

    # 3) Projekt-Update (git pull)
    elif action == "git_update":
        try:
            root = os.path.abspath(os.path.join(current_app.root_path, ".."))
            if os.path.isdir(os.path.join(root, ".git")):
                cmd = "git pull --rebase --autostash"
                out = subprocess.check_output(shlex.split(cmd), cwd=root, stderr=subprocess.STDOUT, text=True)
                flash(f"Update: {out.strip() or 'OK'}", "info")
            else:
                flash("Update: kein Git-Repo gefunden – übersprungen.", "info")
        except Exception as ex:
            flash(f"Update-Fehler: {ex}", "error")

    # 4) Login-Timeout (Minuten) setzen
    elif action == "set_login_timeout":
        val_raw = (request.form.get("login_timeout_minutes") or "").strip()
        try:
            minutes = int(val_raw)
            if minutes < 1 or minutes > 7 * 24 * 60:  # bis 7 Tage
                raise ValueError()
            set_setting("login_timeout_minutes", str(minutes))
            flash(f"Login-Timeout auf {minutes} Minuten gesetzt.", "success")
        except ValueError:
            flash("Bitte eine Zahl zwischen 1 und 10080 (Minuten) angeben.", "error")

    else:
        flash("Unbekannte Aktion.", "error")

    # Zurück aufs Dashboard
    return redirect(url_for("core.index"))
