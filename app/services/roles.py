# app/services/roles.py
from functools import wraps
from typing import Callable, Iterable, Optional
from flask import session, abort

# === Rollenmodell ===
# Reihenfolge bestimmt ">= Rechte"
ROLE_ORDER = ["viewer", "editor", "admin"]
DEFAULT_ROLE = "viewer"

# Policy: Welche Rolle wird für welche Aktion minimal benötigt?
POLICY = {
    "upload": "editor",          # Medien hochladen/löschen
    "playlist_write": "editor",  # Playlist bearbeiten (Add/Remove/Sort/Dauer)
    "player_control": "editor",  # Play/Pause/Next/Prev
    "system_view": "editor",     # z.B. Systeminfos-Kachel
    "system_upgrade": "admin",   # OTA-Update/Neustart
    "user_admin": "admin",       # Benutzerverwaltung/Rollen ändern
}

def _normalize_role(v: Optional[str]) -> str:
    if not v:
        return DEFAULT_ROLE
    v = str(v).strip().lower()
    # häufige Synonyme
    if v in {"administrator", "superuser", "superadmin"}:
        v = "admin"
    if v not in ROLE_ORDER:
        return DEFAULT_ROLE
    return v

def get_current_role() -> str:
    """Ermittelt die aktuelle Rolle – robust gegen verschiedene Session-Strukturen."""
    # 1) direkte Rolle
    role = session.get("role")
    # 2) verschachtelte User-Strukturen, die häufig vorkommen
    if not role:
        user = session.get("user") or {}
        role = user.get("role") or user.get("type") or user.get("account_role")
    # 3) weitere populäre Keys
    if not role:
        role = session.get("user_role") or session.get("account_role")
    return _normalize_role(role)

def has_role(required: str) -> bool:
    """Prüft, ob aktuelle Rolle >= erforderlicher Rolle ist."""
    cur = get_current_role()
    try:
        return ROLE_ORDER.index(cur) >= ROLE_ORDER.index(_normalize_role(required))
    except ValueError:
        return False

def can(action: str) -> bool:
    """Prüft anhand der POLICY, ob die aktuelle Rolle die Aktion darf."""
    required = POLICY.get(action, "admin")  # unbekannte Aktionen: nur Admin
    return has_role(required)

def require_role(required: str) -> Callable:
    """Decorator: Route nur zulassen, wenn Rolle >= required."""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not has_role(required):
                abort(403)
            return fn(*args, **kwargs)
        return wrapper
    return decorator

def require_any_role(roles: Iterable[str]) -> Callable:
    """Decorator: eine von mehreren Rollen erlaubt (>= Logik je Rolle)."""
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if any(has_role(r) for r in roles):
                return fn(*args, **kwargs)
            abort(403)
        return wrapper
    return decorator
