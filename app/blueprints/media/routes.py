import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, send_file, abort, jsonify
from werkzeug.exceptions import RequestEntityTooLarge
from sqlalchemy import select
from app.db import get_session
from app.models.media import Media
# Beide Modelle möglich – im Altzustand heißt es Category, im Neu-Zustand Folder
try:
    from app.models.folder import Folder as FolderModel
except Exception:
    FolderModel = None  # type: ignore

try:
    from app.models.category import Category as CategoryModel
except Exception:
    CategoryModel = None  # type: ignore

from app.services.media_service import (
    add_media_record,
    get_media as svc_get_media,
    is_allowed_mime,
    secure_unique_path,
    ensure_thumbnail,
    probe_video_duration_seconds,
)
# Services für Ordner/Kategorien – je nachdem was vorhanden ist
try:
    from app.services.folder_service import list_folders as svc_list_folders, create_folder as svc_create_folder
except Exception:
    svc_list_folders = None  # type: ignore
    svc_create_folder = None  # type: ignore

try:
    from app.services.category_service import list_categories as svc_list_categories, create_category as svc_create_category
except Exception:
    svc_list_categories = None  # type: ignore
    svc_create_category = None  # type: ignore

from app.services.playlist_service import get_or_create_default_playlist, add_item_to_playlist_end
from app.blueprints.auth.routes import role_required

media_bp = Blueprint("media", __name__)

# ---------- helpers: schema-agnostic ----------
def has_attr(obj, name: str) -> bool:
    return hasattr(obj, name)

def get_folder_list(db):
    """Gibt Liste von Ordnern/Kategorien als [{'id', 'name'}] zurück."""
    if svc_list_folders:
        fs = svc_list_folders(db)
        return [{"id": f.id, "name": f.name} for f in fs]
    elif svc_list_categories:
        cs = svc_list_categories(db)
        return [{"id": c.id, "name": c.name} for c in cs]
    else:
        return []

def create_folder(db, name: str):
    """Erzeugt Ordner oder Kategorie und gibt (id, name) zurück."""
    if svc_create_folder:
        f = svc_create_folder(db, name)
        return f.id, f.name
    elif svc_create_category:
        c = svc_create_category(db, name)
        return c.id, c.name
    else:
        raise RuntimeError("No folder/category service available")

def resolve_container_by_id(db, id_: int):
    """Hole Folder/Category Objekt; gibt None wenn nicht gefunden."""
    if id_ is None:
        return None
    if FolderModel is not None:
        obj = db.get(FolderModel, id_)
        if obj:
            return obj
    if CategoryModel is not None:
        obj = db.get(CategoryModel, id_)
        if obj:
            return obj
    return None

def assign_media_container(m: Media, container_id: int | None):
    """Setzt m.folder_id ODER m.category_id – je nach vorhandenem Schema."""
    if container_id in (None, "", "null"):  # entfernen
        if has_attr(m, "folder_id"):
            m.folder_id = None  # type: ignore
        if has_attr(m, "category_id"):
            m.category_id = None  # type: ignore
        return

    # setze die passende Spalte
    if has_attr(m, "folder_id"):
        m.folder_id = int(container_id)  # type: ignore
    if has_attr(m, "category_id"):
        m.category_id = int(container_id)  # type: ignore

def attach_folder_alias(items):
    """Sorgt dafür, dass Templates mit m.folder arbeiten können,
    auch wenn es nur m.category gibt.
    """
    for m in items:
        if not hasattr(m, "folder") and hasattr(m, "category"):
            try:
                # alias properties für Template
                object.__setattr__(m, "folder", getattr(m, "category"))
            except Exception:
                pass
        # gleiches Spiel für IDs (für data-cat-id)
        if not hasattr(m, "folder_id") and hasattr(m, "category_id"):
            try:
                object.__setattr__(m, "folder_id", getattr(m, "category_id"))
            except Exception:
                pass


@media_bp.app_errorhandler(RequestEntityTooLarge)
def handle_file_too_large(e):
    max_mb = int(current_app.config.get("MAX_CONTENT_LENGTH", 0) / (1024 * 1024))
    flash(f"Upload zu groß. Maximal erlaubt: {max_mb} MB pro Upload.", "error")
    return redirect(url_for("core.index")), 413


# ---------------------- LIST / GRID ----------------------
@media_bp.route("/", methods=["GET"])
def list_media():
    folder_id = request.args.get("folder_id", type=int)

    db = get_session()
    try:
        folders = get_folder_list(db)

        q = select(Media)
        # Filter je nach vorhandener Spalte
        if folder_id:
            if has_attr(Media, "folder_id"):
                q = q.where(Media.folder_id == folder_id)  # type: ignore[attr-defined]
            elif has_attr(Media, "category_id"):
                q = q.where(Media.category_id == folder_id)  # type: ignore[attr-defined]

        items = list(db.scalars(q.order_by(Media.id.desc())).all())

        # Alias m.folder / m.folder_id herstellen, wenn nötig
        attach_folder_alias(items)

        # Active-Folder Objekt (nur für Titelanzeige optional)
        active_folder = resolve_container_by_id(db, folder_id) if folder_id else None

        return render_template("media_grid.html",
                               items=items,
                               folders=folders,
                               active_folder=active_folder)
    finally:
        db.close()


@media_bp.route("/playlist", methods=["GET"])
@role_required(("admin", "editor"))
def playlist_manage():
    return render_template("media_playlist.html")


# ---------------------- UPLOAD ----------------------
@media_bp.route("/upload", methods=["POST"])
@role_required(("admin", "editor"))
def upload_media():
    f = request.files.get("file")

    # akzeptiere beide Keys (Kompatibilität)
    target_id = request.form.get("target_folder_id", type=int) \
        or request.form.get("category_id", type=int)

    if not f or f.filename == "":
        if "application/json" in (request.headers.get("Accept") or ""):
            return jsonify({"ok": False, "error": "no file"}), 400
        flash("Keine Datei ausgewählt.", "error")
        return redirect(url_for("core.index"))

    allowed_prefixes = current_app.config.get("ALLOWED_MIME_PREFIXES", ("image/", "video/"))
    if not is_allowed_mime(f.mimetype or "", allowed_prefixes):
        msg = "Nicht unterstützter Dateityp. Erlaubt sind nur Bilder und Videos."
        if "application/json" in (request.headers.get("Accept") or ""):
            return jsonify({"ok": False, "error": msg}), 400
        flash(msg, "error")
        return redirect(url_for("core.index"))

    media_dir = os.path.abspath(os.path.join(current_app.root_path, ".", "media"))
    thumbs_dir = os.path.join(media_dir, "_thumbs")
    os.makedirs(media_dir, exist_ok=True)
    os.makedirs(thumbs_dir, exist_ok=True)

    safe_name, save_path = secure_unique_path(media_dir, f.filename)
    f.save(save_path)

    duration = None
    if (f.mimetype or "").startswith("video/"):
        duration = probe_video_duration_seconds(save_path)

    db = get_session()
    try:
        m = add_media_record(
            db,
            filename=safe_name,
            path=save_path,
            mime=(f.mimetype or "application/octet-stream"),
            duration_s=duration
        )
        if target_id:
            assign_media_container(m, target_id)
        db.commit()

        ensure_thumbnail(m, thumbs_dir)
    finally:
        db.close()

    if "application/json" in (request.headers.get("Accept") or ""):
        # wenn alias, gib folder_id trotzdem zurück
        fid = getattr(m, "folder_id", None) or getattr(m, "category_id", None)
        return jsonify({"ok": True, "id": m.id, "filename": m.filename, "folder_id": fid})

    goto = url_for("media.list_media", folder_id=target_id) if target_id else url_for("media.list_media")
    return redirect(goto)


# ---------------------- RAW / THUMB ----------------------
@media_bp.route("/raw/<int:media_id>")
def raw_media(media_id: int):
    db = get_session()
    try:
        m = svc_get_media(db, media_id)
        if not m or not os.path.isfile(m.path):
            abort(404)
        return send_file(m.path, mimetype=m.mime, as_attachment=False, conditional=True)
    finally:
        db.close()


@media_bp.route("/thumb/<int:media_id>")
def thumb_media(media_id: int):
    db = get_session()
    try:
        m = svc_get_media(db, media_id)
        if not m or not os.path.isfile(m.path):
            abort(404)
        media_dir = os.path.abspath(os.path.join(current_app.root_path, ".", "media"))
        thumbs_dir = os.path.join(media_dir, "_thumbs")
        thumb_path = ensure_thumbnail(m, thumbs_dir)
        return send_file(thumb_path, mimetype="image/jpeg", as_attachment=False, conditional=True)
    finally:
        db.close()


# ---------------------- PLAYLIST QUICK ACTION ----------------------
@media_bp.post("/add_to_active/<int:media_id>")
@role_required(("admin", "editor"))
def add_to_active(media_id: int):
    db = get_session()
    try:
        m = svc_get_media(db, media_id)
        if not m:
            flash("Medium nicht gefunden.", "error")
            return redirect(url_for("media.list_media"))
        active = get_or_create_default_playlist(db)
        add_item_to_playlist_end(db, active.id, media_id, duration=None)
        flash(f"„{m.filename}“ zur aktiven Playlist hinzugefügt.", "success")
    finally:
        db.close()
    return redirect(url_for("media.list_media"))


# ---------------------- RENAME / DELETE ----------------------
@media_bp.post("/rename/<int:media_id>")
@role_required(("admin", "editor"))
def rename_media(media_id: int):
    new_name = (request.form.get("new_name") or "").strip()
    if not new_name:
        flash("Neuer Name darf nicht leer sein.", "error")
        return redirect(url_for("media.list_media"))

    db = get_session()
    try:
        m = db.get(Media, media_id)
        if not m:
            flash("Medium nicht gefunden.", "error")
        else:
            m.filename = new_name
            db.commit()
            flash("Name aktualisiert.", "success")
    finally:
        db.close()
    return redirect(url_for("media.list_media"))


@media_bp.post("/delete/<int:media_id>")
@role_required(("admin", "editor"))
def delete_media(media_id: int):
    db = get_session()
    try:
        m = db.get(Media, media_id)
        if not m:
            flash("Medium nicht gefunden.", "error")
            return redirect(url_for("media.list_media"))

        try:
            if m.path and os.path.isfile(m.path):
                os.remove(m.path)
            media_dir = os.path.abspath(os.path.join(current_app.root_path, ".", "media"))
            thumbs_dir = os.path.join(media_dir, "_thumbs")
            for name in os.listdir(thumbs_dir) if os.path.isdir(thumbs_dir) else []:
                if name.endswith("_thumb.jpg") and name.startswith(os.path.splitext(os.path.basename(m.filename))[0]):
                    try:
                        os.remove(os.path.join(thumbs_dir, name))
                    except Exception:
                        pass
        except Exception:
            pass

        db.delete(m)
        db.commit()
        flash("Medium gelöscht.", "success")
    finally:
        db.close()
    return redirect(url_for("media.list_media"))


# ---------------------- FOLDERS: API & BULK MOVE ----------------------
@media_bp.get("/api/folders")
def api_list_folders():
    db = get_session()
    try:
        return jsonify({"folders": get_folder_list(db)})
    finally:
        db.close()


@media_bp.post("/api/folders")
@role_required(("admin", "editor"))
def api_create_folder():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    db = get_session()
    try:
        fid, fname = create_folder(db, name)
        return jsonify({"ok": True, "folder": {"id": fid, "name": fname}})
    finally:
        db.close()


@media_bp.post("/api/media/<int:media_id>/folder")
@role_required(("admin", "editor"))
def api_assign_folder(media_id: int):
    data = request.get_json(silent=True) or {}
    folder_id = data.get("folder_id", None)

    db = get_session()
    try:
        m = db.get(Media, media_id)
        if not m:
            return jsonify({"ok": False, "error": "media not found"}), 404

        if folder_id not in (None, "", "null"):
            if not resolve_container_by_id(db, int(folder_id)):
                return jsonify({"ok": False, "error": "folder not found"}), 404

        assign_media_container(m, folder_id)
        db.commit()

        fid = getattr(m, "folder_id", None) or getattr(m, "category_id", None)
        return jsonify({"ok": True, "folder_id": fid})
    finally:
        db.close()


@media_bp.post("/move_to_folder")
@role_required(("admin", "editor"))
def move_to_folder():
    folder_id = request.form.get("folder_id", type=int)
    ids = request.form.getlist("media_ids[]", type=int)

    db = get_session()
    try:
        # check target exists if provided
        if folder_id and not resolve_container_by_id(db, folder_id):
            flash("Ziel-Ordner existiert nicht.", "error")
            return redirect(url_for("media.list_media"))

        count = 0
        for mid in ids:
            m = db.get(Media, mid)
            if not m:
                continue
            assign_media_container(m, folder_id)
            count += 1
        db.commit()
        flash(f"{count} Datei(en) verschoben.", "success")
        return redirect(url_for("media.list_media", folder_id=folder_id))
    finally:
        db.close()


# ---------------------- COMPAT: "categories" Spiegel-Endpoints ----------------------
@media_bp.get("/api/categories")
def api_list_categories_compat():
    db = get_session()
    try:
        # gleiche Liste, anderer Schlüssel
        cats = get_folder_list(db)
        # parent_id ist im flachen Modell None
        return jsonify({"categories": [{"id": c["id"], "name": c["name"], "parent_id": None} for c in cats]})
    finally:
        db.close()


@media_bp.post("/api/categories")
@role_required(("admin", "editor"))
def api_create_category_compat():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    db = get_session()
    try:
        fid, fname = create_folder(db, name)
        return jsonify({"ok": True, "category": {"id": fid, "name": fname, "parent_id": None}})
    finally:
        db.close()


@media_bp.post("/api/media/<int:media_id>/category")
@role_required(("admin", "editor"))
def api_assign_category_compat(media_id: int):
    """Akzeptiert {category_id} und schreibt in folder_id ODER category_id – je nach Schema."""
    data = request.get_json(silent=True) or {}
    cat_id = data.get("category_id", None)

    db = get_session()
    try:
        m = db.get(Media, media_id)
        if not m:
            return jsonify({"ok": False, "error": "media not found"}), 404

        if cat_id not in (None, "", "null"):
            if not resolve_container_by_id(db, int(cat_id)):
                return jsonify({"ok": False, "error": "folder not found"}), 404

        assign_media_container(m, cat_id)
        db.commit()

        fid = getattr(m, "folder_id", None) or getattr(m, "category_id", None)
        return jsonify({"ok": True, "folder_id": fid, "category_id": fid})
    finally:
        db.close()
