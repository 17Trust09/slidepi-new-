# app/services/tag_service.py
from __future__ import annotations
from typing import Iterable, List
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.tag import Tag
from app.models.media import Media

def list_all_tags(db: Session) -> List[str]:
    rows = db.execute(select(Tag).order_by(Tag.name.asc())).scalars().all()
    return [t.name for t in rows]

def _ensure_tags(db: Session, names: Iterable[str]) -> List[Tag]:
    norm = [t.strip() for t in names if t and t.strip()]
    if not norm:
        return []
    existing = {t.name: t for t in db.execute(select(Tag).where(Tag.name.in_(norm))).scalars().all()}
    created: List[Tag] = []
    for name in norm:
        if name not in existing:
            t = Tag(name=name)
            db.add(t)
            db.flush()
            existing[name] = t
            created.append(t)
    return [existing[n] for n in norm]

def add_tags_to_media(db: Session, media_id: int, tags: Iterable[str]) -> bool:
    m = db.get(Media, media_id)
    if not m:
        return False
    to_add = _ensure_tags(db, tags)
    current_ids = {t.id for t in m.tags}
    for t in to_add:
        if t.id not in current_ids:
            m.tags.append(t)
    db.commit()
    db.refresh(m)
    return True

def set_tags_for_media(db: Session, media_id: int, tags: Iterable[str]) -> bool:
    """Ersetzt komplette Tag-Liste des Mediums."""
    m = db.get(Media, media_id)
    if not m:
        return False
    m.tags.clear()
    to_add = _ensure_tags(db, tags)
    for t in to_add:
        m.tags.append(t)
    db.commit()
    db.refresh(m)
    return True

def remove_tag_from_media(db: Session, media_id: int, tag_name: str) -> bool:
    m = db.get(Media, media_id)
    if not m:
        return False
    tag = next((t for t in m.tags if t.name == tag_name), None)
    if not tag:
        return False
    m.tags.remove(tag)
    db.commit()
    return True
