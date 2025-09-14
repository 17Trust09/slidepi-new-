# app/services/category_service.py
from __future__ import annotations
from typing import Optional, List, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models.category import Category

def list_categories(db: Session) -> List[Category]:
    return db.execute(
        select(Category).order_by(Category.parent_id.nullsfirst(), Category.name.asc())
    ).scalars().all()

def list_categories_serialized(db: Session) -> List[Dict[str, Any]]:
    cats = list_categories(db)
    return [{"id": c.id, "name": c.name, "parent_id": c.parent_id} for c in cats]

def create_category(db: Session, name: str, parent_id: Optional[int] = None) -> Category:
    slug = name.strip().lower().replace(" ", "-")[:120] or "cat"
    c = Category(name=name.strip(), parent_id=parent_id, slug=slug)
    db.add(c); db.commit(); db.refresh(c)
    return c

def rename_category(db: Session, cat_id: int, new_name: str) -> bool:
    c = db.get(Category, cat_id)
    if not c: return False
    c.name = new_name.strip()
    db.commit()
    return True

def delete_category(db: Session, cat_id: int) -> bool:
    c = db.get(Category, cat_id)
    if not c: return False
    db.delete(c)
    db.commit()
    return True
