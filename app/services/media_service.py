import os
import itertools
import math
import subprocess
import shutil
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.orm import Session
from werkzeug.utils import secure_filename
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy.orm import selectinload
from app.models.media import Media

# ===== Datenbank-Operationen =====

def list_media(db: Session) -> List[Media]:
    stmt = (
        select(Media)
        .options(selectinload(Media.tags))   # lädt Tags effizient separat
        .order_by(Media.uploaded_at.desc())
    )
    # unique() ist mit selectin nicht nötig, schadet aber nicht -> weglassen ok
    return db.execute(stmt).scalars().all()

def add_media_record(db: Session, filename: str, path: str, mime: str, duration_s: Optional[int] = None) -> Media:
    m = Media(filename=filename, path=path, mime=mime, duration_s=duration_s)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m

def get_media(db: Session, media_id: int) -> Optional[Media]:
    return db.get(Media, media_id)

# ===== Hilfsfunktionen =====

def guess_kind(mime: str) -> str:
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("image/"):
        return "image"
    return "file"

def file_exists(media: Media) -> bool:
    return os.path.isfile(media.path)

def is_allowed_mime(mime: str, allowed_prefixes: tuple[str, ...]) -> bool:
    """Erlaubt nur MIME-Typen mit angegebenen Präfixen (z. B. image/*, video/*)."""
    if not mime:
        return False
    return any(mime.startswith(pref) for pref in allowed_prefixes)

def secure_unique_path(directory: str, raw_filename: str) -> tuple[str, str]:
    """
    Erzeugt einen sicheren, eindeutigen Dateinamen in 'directory'.
    Rückgabe: (finaler_name, finaler_absoluter_pfad)
    """
    os.makedirs(directory, exist_ok=True)
    base = secure_filename(raw_filename)
    if not base:
        base = "upload"

    name, ext = os.path.splitext(base)
    candidate = base
    target = os.path.join(directory, candidate)

    # Falls Datei existiert → _1, _2, ...
    for i in itertools.count(1):
        if not os.path.exists(target):
            return candidate, target
        candidate = f"{name}_{i}{ext}"
        target = os.path.join(directory, candidate)

# ===== ffprobe / Dauer-Erkennung =====

def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None

def probe_video_duration_seconds(path: str) -> Optional[int]:
    """Liest Videodauer via ffprobe; gibt Sekunden als int zurück oder None."""
    if not ffprobe_available() or not os.path.exists(path):
        return None
    try:
        # ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 input
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stderr=subprocess.STDOUT
        ).decode("utf-8", errors="ignore").strip()
        if not out:
            return None
        # round to nearest second
        return int(round(float(out)))
    except Exception:
        return None

# ===== Thumbnails =====

def thumb_filename_for(media: Media) -> str:
    base_name = os.path.splitext(os.path.basename(media.filename))[0]
    return f"{base_name}_thumb.jpg"

def ensure_thumbnail(media: Media, thumbs_dir: str, max_size: int = 320) -> str:
    """
    Stellt sicher, dass ein Thumbnail existiert. Gibt den Pfad zum Thumbnail zurück.
    - Bilder: mit Pillow skaliert
    - Videos: wenn möglich ffmpeg Snapshot, sonst Placeholder mit "VIDEO"
    - Andere: Placeholder mit "FILE"
    """
    os.makedirs(thumbs_dir, exist_ok=True)
    thumb_path = os.path.join(thumbs_dir, thumb_filename_for(media))
    if os.path.exists(thumb_path):
        return thumb_path

    kind = guess_kind(media.mime)

    if kind == "image":
        try:
            with Image.open(media.path) as img:
                img.thumbnail((max_size, max_size))
                # nach RGB konvertieren (falls PNG mit Alpha)
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(thumb_path, format="JPEG", quality=85)
                return thumb_path
        except Exception:
            # fallback placeholder
            return _make_placeholder(thumb_path, text="IMAGE", max_size=max_size)

    if kind == "video":
        # Versuchen wir einen Frame (1s) zu rendern
        if shutil.which("ffmpeg"):
            try:
                # ffmpeg -ss 00:00:01 -i input -frames:v 1 -vf scale='min(320,iw)':-1 output.jpg
                subprocess.check_call([
                    "ffmpeg", "-y",
                    "-ss", "00:00:01", "-i", media.path,
                    "-frames:v", "1",
                    "-vf", f"scale='min({max_size},iw)':-1",
                    thumb_path
                ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if os.path.exists(thumb_path):
                    return thumb_path
            except Exception:
                pass
        # Fallback: Placeholder
        return _make_placeholder(thumb_path, text="VIDEO", max_size=max_size)

    # Sonstige Dateien → Placeholder
    return _make_placeholder(thumb_path, text="FILE", max_size=max_size)

def _make_placeholder(path: str, text: str, max_size: int = 320) -> str:
    bg = (16, 22, 33)       # dunkles Blau
    fg = (124, 193, 255)    # helles Blau
    img = Image.new("RGB", (max_size, max_size), bg)
    draw = ImageDraw.Draw(img)
    # Schriftgröße dynamisch
    size = 32
    try:
        # Wenn keine TrueType-Font verfügbar, nimmt Pillow Default
        font = ImageFont.truetype("arial.ttf", size)
    except Exception:
        font = ImageFont.load_default()
    w, h = draw.textsize(text, font=font)
    draw.text(((max_size - w) / 2, (max_size - h) / 2), text, fill=fg, font=font)
    img.save(path, format="JPEG", quality=85)
    return path
