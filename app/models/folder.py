from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import String, Integer
from app.db import Base

class Folder(Base):
    __tablename__ = "folders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    # backref von Media (folder.medias)
    medias: Mapped[list["Media"]] = relationship("Media", back_populates="folder", cascade="all, delete-orphan", passive_deletes=True)

    def __repr__(self) -> str:
        return f"<Folder {self.id}:{self.name}>"
