from __future__ import annotations
from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, DateTime, Text, ForeignKey
from app.db import Base
from app.models.tag import media_tags, Tag
from app.models.folder import Folder

class Media(Base):
    __tablename__ = "media"

    id:          Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename:    Mapped[str] = mapped_column(String(255))
    path:        Mapped[str] = mapped_column(Text)
    mime:        Mapped[str] = mapped_column(String(128))
    duration_s:  Mapped[int | None] = mapped_column(Integer, nullable=True)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Ordner-Zuweisung (flat, keine Unterordner)
    folder_id:   Mapped[int | None] = mapped_column(ForeignKey("folders.id", ondelete="SET NULL"), nullable=True)
    folder:      Mapped[Folder | None] = relationship(Folder, back_populates="medias")

    # Tags (Viele-zu-Vielen)
    tags = relationship(
        Tag,
        secondary=media_tags,
        lazy="selectin",
        backref="media_items",
    )

    def __repr__(self) -> str:
        return f"<Media {self.id}:{self.filename}>"
