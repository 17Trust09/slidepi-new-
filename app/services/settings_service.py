# app/services/settings_service.py
from __future__ import annotations
from typing import Optional, Dict
from sqlalchemy import select
from app.db import get_session
from app.models.system import Setting  # Annahme: Setting liegt in app.models.system

# -------------------------------------------------
# Low-level Helpers
# -------------------------------------------------
def _get_by_key(db, key: str) -> Optional[Setting]:
    return db.execute(select(Setting).where(Setting.key == key)).scalar_one_or_none()

# -------------------------------------------------
# Public API
# -------------------------------------------------
def get_setting(key: str) -> Optional[str]:
    """
    Gibt den Wert des Settings (als str) oder None zurück.
    """
    db = get_session()
    try:
        row = _get_by_key(db, key)
        return row.value if row else None
    finally:
        db.close()

def set_setting(key: str, value: str) -> None:
    """
    Upsert eines Settings.
    """
    db = get_session()
    try:
        row = _get_by_key(db, key)
        if row:
            row.value = value
        else:
            row = Setting(key=key, value=value)
            db.add(row)
        db.commit()
    finally:
        db.close()

def get_settings_dict() -> Dict[str, str]:
    """
    Liefert alle Settings als Dict.
    """
    db = get_session()
    try:
        items = db.execute(select(Setting)).scalars().all()
        return {s.key: s.value for s in items}
    finally:
        db.close()

def ensure_default_settings() -> None:
    """
    Legt Basis-Settings an, sofern sie fehlen.
    """
    defaults = {
        "app_name": "SlidePi",
        "theme": "dark",                   # dark | light | auto
        "default_duration": "10",          # Sekunden
        "login_timeout_minutes": "30",     # Minuten
    }

    db = get_session()
    try:
        existing = {s.key: s.value for s in db.execute(select(Setting)).scalars().all()}
        changed = False
        for k, v in defaults.items():
            if k not in existing:
                db.add(Setting(key=k, value=v))
                changed = True
        if changed:
            db.commit()
    finally:
        db.close()
