from typing import List, Optional, Iterable, Dict, Any
from sqlalchemy import select, delete, func
from sqlalchemy.orm import Session

from app.models.playlist import Playlist, PlaylistItem
from app.models.media import Media


def get_or_create_default_playlist(db: Session) -> Playlist:
    """
    Liefert die aktive Playlist; wenn keine aktiv ist:
    - nimmt 'Default', falls vorhanden, und setzt sie aktiv
    - oder legt 'Default' neu an und setzt sie aktiv
    """
    active = db.execute(
        select(Playlist).where(Playlist.is_active == True)  # noqa: E712
    ).scalars().first()
    if active:
        return active

    pl = db.execute(
        select(Playlist).where(Playlist.name == "Default")
    ).scalars().first()

    if not pl:
        pl = Playlist(name="Default", is_active=True)
        db.add(pl)
        db.commit()
        db.refresh(pl)
    else:
        pl.is_active = True
        db.commit()

    return pl


def list_playlists(db: Session) -> List[Playlist]:
    return db.execute(select(Playlist)).scalars().all()


def set_active_playlist(db: Session, playlist_id: int) -> Optional[Playlist]:
    target = db.get(Playlist, playlist_id)
    if not target:
        return None
    for p in db.execute(select(Playlist)).scalars():
        p.is_active = (p.id == playlist_id)
    db.commit()
    return target


def create_playlist(db: Session, name: str) -> Playlist:
    p = Playlist(name=name, is_active=False)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


def delete_playlist(db: Session, playlist_id: int) -> bool:
    pl = db.get(Playlist, playlist_id)
    if not pl:
        return False
    db.delete(pl)
    db.commit()
    return True


def get_playlist_items(db: Session, playlist_id: int) -> List[PlaylistItem]:
    """
    Gibt die Items der Playlist nach position sortiert zurück.
    """
    return list(
        db.execute(
            select(PlaylistItem).where(PlaylistItem.playlist_id == playlist_id).order_by(PlaylistItem.position.asc())
        ).scalars()
    )


def replace_playlist_items(
    db: Session,
    playlist_id: int,
    media_order: List[int],
    durations: Optional[List[Optional[int]]] = None,
) -> List[PlaylistItem]:
    """
    Ersetzt die komplette Playlist durch `media_order`.
    position startet bei 1, Dauer kommt aus `durations` (falls angegeben) als Sekunden.
    """
    pl = db.get(Playlist, playlist_id)
    if not pl:
        raise ValueError("Playlist existiert nicht")

    db.execute(delete(PlaylistItem).where(PlaylistItem.playlist_id == playlist_id))
    db.commit()

    items: List[PlaylistItem] = []
    for idx, mid in enumerate(media_order, start=1):
        m = db.get(Media, mid)
        if not m:
            continue
        dur = None
        if durations and len(durations) >= idx:
            dval = durations[idx - 1]
            dur = int(dval) if dval not in (None, "", "None") else None
        item = PlaylistItem(
            playlist_id=playlist_id,
            media_id=mid,
            position=idx,
            duration_override_s=dur
        )
        db.add(item)
        items.append(item)

    db.commit()
    return items


def get_active_playlist_with_items(db: Session) -> Optional[Playlist]:
    return db.execute(
        select(Playlist).where(Playlist.is_active == True)  # noqa: E712
    ).scalars().first()


def add_item_to_playlist_end(
    db: Session,
    playlist_id: int,
    media_id: int,
    duration: Optional[int] = None
) -> Optional[PlaylistItem]:
    """
    Hängt ein Medium ans Ende der Playlist und setzt position automatisch (max(position)+1).
    Dauer kann optional überschrieben werden (Sekunden).
    """
    pl = db.get(Playlist, playlist_id)
    if not pl:
        return None

    # höchste Position ermitteln
    max_pos = db.execute(
        select(func.max(PlaylistItem.position)).where(PlaylistItem.playlist_id == playlist_id)
    ).scalar() or 0

    item = PlaylistItem(
        playlist_id=playlist_id,
        media_id=media_id,
        position=max_pos + 1,
        duration_override_s=duration
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def remove_item(db: Session, item_id: int) -> bool:
    """
    Entfernt ein PlaylistItem.
    """
    it = db.get(PlaylistItem, item_id)
    if not it:
        return False
    db.delete(it)
    db.commit()
    return True


def sort_playlist(db: Session, playlist_id: int, ordered_item_ids: Iterable[int]) -> None:
    """
    Setzt die Reihenfolge in der Playlist neu – `position` beginnt bei 1.
    Nur Items, die zur Playlist gehören, werden beeinflusst.
    """
    items = get_playlist_items(db, playlist_id)
    by_id = {it.id: it for it in items}

    pos = 1
    for item_id in ordered_item_ids:
        it = by_id.get(item_id)
        if it and it.playlist_id == playlist_id:
            it.position = pos
            pos += 1

    db.commit()


def set_item_duration(db: Session, item_id: int, duration_s: Optional[int]) -> bool:
    """
    Setzt die Dauer (Sekunden) für ein PlaylistItem. None löscht den Override.
    """
    it = db.get(PlaylistItem, item_id)
    if not it:
        return False
    it.duration_override_s = int(duration_s) if duration_s not in (None, "", "None") else None
    db.commit()
    return True


# ---------------------------
# Feed-Erzeugung für Player
# ---------------------------

def list_active_feed(db: Session, default_duration: int) -> List[Dict[str, Any]]:
    """
    Erzeugt den abgespeckten Feed für den Player:
    - Nur aktive Playlist
    - Nach `position` geordnet
    - Dauer = duration_override_s (falls vorhanden) sonst `default_duration`
    - type = 'image' | 'video'
    - url   -> /media/raw/<media_id>
    - thumb -> /media/thumb/<media_id>
    """
    active = get_or_create_default_playlist(db)
    items = get_playlist_items(db, active.id)

    feed: List[Dict[str, Any]] = []
    for pit in items:
        media: Media = db.get(Media, pit.media_id)
        if not media:
            continue

        mime = (media.mime or "")
        typ = "video" if mime.startswith("video/") else ("image" if mime.startswith("image/") else "unknown")
        if typ == "unknown":
            continue

        duration = pit.duration_override_s if (pit.duration_override_s and pit.duration_override_s > 0) else default_duration

        feed.append({
            "playlist_item_id": pit.id,
            "media_id": media.id,
            "filename": media.filename,
            "type": typ,
            "duration": duration,
            "url": f"/media/raw/{media.id}",
            "thumb": f"/media/thumb/{media.id}",
            # optional:
            "mime": media.mime,
            "width": getattr(media, "width", None),
            "height": getattr(media, "height", None),
        })

    return feed
