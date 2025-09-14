# app/models/tag.py
from __future__ import annotations
from sqlalchemy import Table, Column, Integer, String, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base  # Wichtig: Base kommt aus app.db

# Join-Tabelle: viele-zu-vielen zwischen Media und Tag
media_tags = Table(
    "media_tags",
    Base.metadata,
    Column("media_id", ForeignKey("media.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id",   ForeignKey("tag.id",   ondelete="CASCADE"), primary_key=True),
    UniqueConstraint("media_id", "tag_id", name="uq_media_tag"),
)

class Tag(Base):
    __tablename__ = "tag"

    id:   Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str]  = mapped_column(String(64), unique=True, index=True)

    def __repr__(self) -> str:
        return f"<Tag {self.name}>"
