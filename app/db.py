# app/db.py
from __future__ import annotations
import os
from pathlib import Path
from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# WICHTIG: die gemeinsame Base der Modelle verwenden, nicht neu definieren!
from app.models.base import Base

# --------------------------------------------------------------------
# Pfad: data/slidepi.db
# --------------------------------------------------------------------
DEFAULT_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "slidepi.db"
DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)  # Ordner sicher anlegen

DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")

def _make_engine(url: str):
    connect_args = {"check_same_thread": False} if url.startswith("sqlite:///") else {}
    return create_engine(url, echo=False, future=True, connect_args=connect_args)

engine = _make_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

# --------------------------------------------------------------------
# Sessions
# --------------------------------------------------------------------
def get_session():
    """
    Liefert eine *neue* Session-Instanz zurück.
    Aufrufer ist für commit()/rollback()/close() verantwortlich.
    """
    return SessionLocal()

@contextmanager
def session_scope():
    """
    Optionaler Context-Manager:
      with session_scope() as db:
          ...
    """
    db = get_session()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# --------------------------------------------------------------------
# SQLite – Checks & Mini-Migration
# --------------------------------------------------------------------
def _sqlite_table_exists(conn, name: str) -> bool:
    r = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"),
        {"n": name},
    ).fetchone()
    return r is not None

def _sqlite_column_exists(conn, table: str, col: str) -> bool:
    rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    # PRAGMA table_info: (cid, name, type, notnull, dflt_value, pk)
    return any(row[1] == col for row in rows)

def _ensure_core_tables():
    """
    Falls Base.metadata.create_all() aus irgendeinem Grund etwas nicht angelegt hat,
    legen wir die Kern-Tabellen defensiv an (nur wenn fehlend).
    """
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")

        if not _sqlite_table_exists(conn, "settings"):
            conn.exec_driver_sql("""
                CREATE TABLE settings (
                  "key"   VARCHAR(64) PRIMARY KEY,
                  "value" TEXT
                );
            """)

        if not _sqlite_table_exists(conn, "tag"):
            conn.exec_driver_sql("""
                CREATE TABLE tag (
                  id   INTEGER PRIMARY KEY AUTOINCREMENT,
                  name VARCHAR(64) UNIQUE
                );
            """)

        if not _sqlite_table_exists(conn, "category"):
            conn.exec_driver_sql("""
                CREATE TABLE category (
                  id        INTEGER PRIMARY KEY AUTOINCREMENT,
                  name      VARCHAR(96) NOT NULL,
                  slug      VARCHAR(120) NOT NULL,
                  parent_id INTEGER,
                  CONSTRAINT uq_cat_parent_name UNIQUE (parent_id, name),
                  FOREIGN KEY(parent_id) REFERENCES category(id) ON DELETE SET NULL
                );
            """)

        if not _sqlite_table_exists(conn, "media_tags"):
            conn.exec_driver_sql("""
                CREATE TABLE media_tags (
                  media_id INTEGER NOT NULL,
                  tag_id   INTEGER NOT NULL,
                  PRIMARY KEY (media_id, tag_id),
                  FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE,
                  FOREIGN KEY(tag_id)   REFERENCES tag(id)   ON DELETE CASCADE
                );
            """)

def _sqlite_safe_migrate():
    """
    Kleine Migration für bestehende SQLite-DB:
    - Spalte media.category_id anhängen, falls sie fehlt.
    """
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA foreign_keys=ON")

        if _sqlite_table_exists(conn, "media") and not _sqlite_column_exists(conn, "media", "category_id"):
            conn.exec_driver_sql(
                "ALTER TABLE media ADD COLUMN category_id INTEGER REFERENCES category(id) ON DELETE SET NULL"
            )

# --------------------------------------------------------------------
# Init DB (auf App-Start)
# --------------------------------------------------------------------
def init_db(url: str | None = None):
    """
    Initialisiert die Datenbank.
    - Optional: URL-Override (Tests/Config).
    - Registriert Modelle, legt fehlende Tabellen an.
    - Stellt sicher, dass Kern-Tabellen existieren.
    - Führt Mini-Migrationen aus.
    """
    global engine, SessionLocal

    # Optional URL übernehmen
    if url:
        engine = _make_engine(url)
        SessionLocal.configure(bind=engine)

    # Modelle importieren, damit ihre Tabellen bei Base registriert werden
    from app.models import user, system, playlist, category, tag, media, setting  # noqa: F401

    # Tabellen erstellen (nur fehlende)
    Base.metadata.create_all(bind=engine)

    # Safety-Net: Kern-Tabellen sicherstellen
    _ensure_core_tables()

    # Mini-Migrationen (SQLite)
    try:
        _sqlite_safe_migrate()
    except Exception as e:
        print("[DB] Mini-Migration fehlgeschlagen:", e)
