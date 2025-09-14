# app/models/setting.py
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from . import Base

class Setting(Base):
    __tablename__ = "settings"

    # Bestehende DB hat offenbar KEIN 'id'.
    # Wir passen das ORM an: 'key' ist der Primärschlüssel.
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(String(2048), nullable=False, default="")
