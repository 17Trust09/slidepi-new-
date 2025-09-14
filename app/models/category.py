# app/models/category.py
from __future__ import annotations
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import Integer, String, ForeignKey, UniqueConstraint
from app.db import Base

class Category(Base):
    __tablename__ = "category"

    id:        Mapped[int]  = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:      Mapped[str]  = mapped_column(String(96))
    slug:      Mapped[str]  = mapped_column(String(120))
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("category.id", ondelete="SET NULL"), nullable=True)

    parent = relationship("Category", remote_side="Category.id", backref="children")

    __table_args__ = (
        UniqueConstraint("parent_id", "name", name="uq_cat_parent_name"),
    )

    def __repr__(self) -> str:
        return f"<Category {self.name}>"
