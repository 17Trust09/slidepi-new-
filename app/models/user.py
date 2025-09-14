from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String
from app.models.base import Base

VALID_ROLES = ("admin", "editor", "user")

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="user")

    def is_admin(self) -> bool:
        return self.role == "admin"

    def is_editor(self) -> bool:
        return self.role == "editor"

    def has_any_role(self, *roles: str) -> bool:
        return self.role in roles
