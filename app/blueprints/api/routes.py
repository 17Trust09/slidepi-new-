# app/blueprints/api/routes.py
from __future__ import annotations
from typing import List, Dict, Any
from flask import Blueprint, jsonify, request, make_response
from app.db import get_session

from app.services.settings_service import get_setting
from app.services.playlist_service import (
    get_or_create_default_playlist,
    get_playlist_items,
    sort_playlist,
    remove_item,
    list_active_feed,
    set_item_duration,
)
from app.blueprints.auth.routes import role_required

# NEU: Services & Modelle für Tags/Kategorien
from app.services.tag_service import (
    list_all_tags,
    add_tags_to_media,
    remove_tag_from_media,
    set_tags_for_media,
)
from app.services.category_service import (
    list_categories_serialized,
    create_category,
)
from app.models.media import Media

import os, sys, time, platform, shutil, hashlib, json

try:
    import psutil  # type: ignore
except Exception:
    psutil = None  # type: ignore

api_bp = Blueprint("api", __name__)

# -----------------------
# Helpers
# -----------------------
def _feed_etag(feed_payload: list[dict[str, Any]]) -> str:
    serial = json.dumps(
        [
            {
                "media_id": it.get("media_id"),
                "duration": it.get("duration"),
                "mime": it.get("mime"),
                "path": it.get("path"),
            }
            for it in feed_payload
        ],
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8", errors="ignore")
    return hashlib.sha256(serial).hexdigest()

# -----------------------
# Feed für den Player (mit ETag/304)
# -----------------------
@api_bp.get("/feed")
def api_feed():
    raw = get_setting("default_duration")
    try:
        default_duration = int(raw) if raw is not None and str(raw).strip() else 10
    except (TypeError, ValueError):
        default_duration = 10

    db = get_session()
    try:
        payload = list_active_feed(db, default_duration=default_duration)
        etag = _feed_etag(payload)

        inm = request.headers.get("If-None-Match")
        if inm and inm == etag:
            resp = make_response("", 304)
            resp.headers["ETag"] = etag
            resp.headers["Cache-Control"] = "no-store"
            return resp

        resp = jsonify({"ok": True, "feed": payload})
        resp.headers["ETag"] = etag
        resp.headers["Cache-Control"] = "no-store"
        return resp
    except Exception as e:
        return jsonify({"ok": False, "error": f"feed-error: {e}"}), 500
    finally:
        db.close()

# -----------------------
# Aktive Playlist (für Dashboard)
# -----------------------
@api_bp.get("/playlist/active")
def api_playlist_active():
    db = get_session()
    try:
        active = get_or_create_default_playlist(db)
        items = get_playlist_items(db, active.id)
        return jsonify({
            "ok": True,
            "playlist": {"id": active.id, "name": active.name, "is_active": True},
            "items": [{"id": it.id, "media_id": it.media_id, "position": it.position} for it in items],
        })
    finally:
        db.close()

# -----------------------
# Playlist Utilities (Editor/Admin)
# -----------------------
@api_bp.post("/playlist/sort")
@role_required(("admin", "editor"))
def api_playlist_sort():
    data = request.get_json(silent=True) or {}
    order: List[int] = data.get("order") or []
    if not isinstance(order, list) or not all(isinstance(x, int) for x in order):
        return jsonify({"ok": False, "error": "Invalid 'order' payload"}), 400

    db = get_session()
    try:
        active = get_or_create_default_playlist(db)
        sort_playlist(db, active.id, order)
        return jsonify({"ok": True, "changed": True})
    finally:
        db.close()

@api_bp.post("/playlist/remove")
@role_required(("admin", "editor"))
def api_playlist_remove():
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")
    if not isinstance(item_id, int):
        return jsonify({"ok": False, "error": "Invalid 'item_id'"}), 400

    db = get_session()
    try:
        ok = remove_item(db, item_id)
        if not ok:
            return jsonify({"ok": False, "error": "Item not found"}), 404
        return jsonify({"ok": True, "changed": True})
    finally:
        db.close()

@api_bp.post("/playlist/set_duration")
@role_required(("admin", "editor"))
def api_playlist_set_duration():
    data = request.get_json(silent=True) or {}
    item_id = data.get("item_id")
    duration = data.get("duration")  # kann None sein

    if not isinstance(item_id, int):
        return jsonify({"ok": False, "error": "Invalid 'item_id'"}), 400
    if duration is not None and not isinstance(duration, int):
        return jsonify({"ok": False, "error": "Invalid 'duration'"}), 400

    db = get_session()
    try:
        ok = set_item_duration(db, item_id, duration)
        if not ok:
            return jsonify({"ok": False, "error": "Item not found"}), 404
        return jsonify({"ok": True, "changed": True})
    finally:
        db.close()

# -----------------------
# Systeminfo (Dashboard)
# -----------------------
def _systeminfo() -> Dict[str, Any]:
    info: Dict[str, Any] = {}
    try:
        info["os"] = f"{platform.system()} {platform.release()} ({platform.machine()})"
    except Exception:
        info["os"] = platform.platform(terse=True)
    info["python"] = (sys.version.split()[0] if sys.version else "")
    try:
        info["cpu_count"] = os.cpu_count() or 0
    except Exception:
        info["cpu_count"] = 0
    if psutil:
        try:
            info["cpu_load_percent"] = float(psutil.cpu_percent(interval=0.3))
        except Exception:
            info["cpu_load_percent"] = None
    else:
        info["cpu_load_percent"] = None
    if psutil:
        try:
            vm = psutil.virtual_memory()
            info["ram_total_mb"] = int(vm.total / (1024 * 1024))
            info["ram_used_mb"] = int(vm.used / (1024 * 1024))
            info["ram_percent"] = float(vm.percent)
        except Exception:
            info["ram_total_mb"] = info["ram_used_mb"] = info["ram_percent"] = None
    else:
        info["ram_total_mb"] = info["ram_used_mb"] = info["ram_percent"] = None
    try:
        total, used, _free = shutil.disk_usage(os.getcwd())
        info["disk_total_gb"] = round(total / (1024 ** 3), 2)
        info["disk_used_gb"] = round(used / (1024 ** 3), 2)
        info["disk_percent"] = round((used / total) * 100, 1) if total else None
    except Exception:
        info["disk_total_gb"] = info["disk_used_gb"] = info["disk_percent"] = None
    try:
        if psutil and hasattr(psutil, "boot_time"):
            boot = psutil.boot_time()
            info["uptime_seconds"] = int(time.time() - boot)
        else:
            if not hasattr(_systeminfo, "_start"):
                _systeminfo._start = time.time()  # type: ignore[attr-defined]
            info["uptime_seconds"] = int(time.time() - getattr(_systeminfo, "_start"))  # type: ignore[attr-defined]
    except Exception:
        info["uptime_seconds"] = None
    return info

@api_bp.get("/system/info")
def api_system_info():
    try:
        data = _systeminfo()
        return jsonify({"ok": True, "info": data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@api_bp.get("/systeminfo")
def api_system_info_alias():
    return api_system_info()

# -----------------------
# Login-Timeout (für Dashboard-Anzeige)
# -----------------------
@api_bp.get("/settings/login_timeout")
def api_login_timeout():
    """
    Liefert den konfigurierten Login-Timeout in Minuten.
    Fällt auf 30 zurück, wenn Setting fehlt/ungültig.
    """
    raw = get_setting("login_timeout_minutes")
    try:
        minutes = int(raw) if raw is not None and str(raw).strip() else 30
    except (TypeError, ValueError):
        minutes = 30
    return jsonify({"ok": True, "minutes": minutes})

# -----------------------
# Tags
# -----------------------
@api_bp.get("/tags")
def api_list_tags():
    db = get_session()
    try:
        return jsonify({"ok": True, "tags": list_all_tags(db)})
    finally:
        db.close()

@api_bp.post("/media/<int:media_id>/tags")
@role_required(("admin", "editor"))
def api_add_tags(media_id: int):
    data = request.get_json(silent=True) or {}
    add = data.get("add") or []
    if not isinstance(add, list):
        return jsonify({"ok": False, "error": "payload 'add' must be a list"}), 400
    db = get_session()
    try:
        ok = add_tags_to_media(db, media_id, add)
        return (jsonify({"ok": True}) if ok else (jsonify({"ok": False, "error": "media not found"}), 404))
    finally:
        db.close()

@api_bp.post("/media/<int:media_id>/tags/set")
@role_required(("admin", "editor"))
def api_set_tags(media_id: int):
    data = request.get_json(silent=True) or {}
    tags = data.get("tags") or []
    if not isinstance(tags, list):
        return jsonify({"ok": False, "error": "payload 'tags' must be a list"}), 400
    db = get_session()
    try:
        ok = set_tags_for_media(db, media_id, tags)
        return (jsonify({"ok": True}) if ok else (jsonify({"ok": False, "error": "media not found"}), 404))
    finally:
        db.close()

@api_bp.delete("/media/<int:media_id>/tags/<string:tag_name>")
@role_required(("admin", "editor"))
def api_remove_tag(media_id: int, tag_name: str):
    db = get_session()
    try:
        ok = remove_tag_from_media(db, media_id, tag_name)
        return (jsonify({"ok": True}) if ok else (jsonify({"ok": False, "error": "not found"}), 404))
    finally:
        db.close()

# -----------------------
# Kategorien (Ordner)
# -----------------------
@api_bp.get("/categories")
def api_list_categories():
    db = get_session()
    try:
        return jsonify({"ok": True, "categories": list_categories_serialized(db)})
    finally:
        db.close()

@api_bp.post("/categories")
@role_required(("admin", "editor"))
def api_create_category():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    parent_id = data.get("parent_id")
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    if parent_id is not None and not isinstance(parent_id, int):
        return jsonify({"ok": False, "error": "parent_id must be int or null"}), 400
    db = get_session()
    try:
        c = create_category(db, name, parent_id)
        return jsonify({"ok": True, "category": {"id": c.id, "name": c.name, "parent_id": c.parent_id}})
    finally:
        db.close()

@api_bp.post("/media/<int:media_id>/category")
@role_required(("admin", "editor"))
def api_set_media_category(media_id: int):
    data = request.get_json(silent=True) or {}
    cat_id = data.get("category_id")
    if cat_id is not None and not isinstance(cat_id, int):
        return jsonify({"ok": False, "error": "category_id must be int or null"}), 400
    db = get_session()
    try:
        m = db.get(Media, media_id)
        if not m:
            return jsonify({"ok": False, "error": "media not found"}), 404
        m.category_id = cat_id if isinstance(cat_id, int) else None
        db.commit()
        return jsonify({"ok": True})
    finally:
        db.close()
