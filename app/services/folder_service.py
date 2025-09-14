from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.folder import Folder

def list_folders(db: Session) -> list[Folder]:
    return list(db.scalars(select(Folder).order_by(Folder.name)).all())

def create_folder(db: Session, name: str) -> Folder:
    name = (name or "").strip()
    if not name:
        raise ValueError("Folder name required")
    # unique erzwingen auf App-Ebene
    existing = db.scalar(select(Folder).where(Folder.name == name))
    if existing:
        return existing
    f = Folder(name=name)
    db.add(f)
    db.commit()
    db.refresh(f)
    return f
