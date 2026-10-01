from sqlalchemy.orm import Mapped, mapped_column

from .base import STRICT, db


class User(db.Model):
    __tablename__ = 'users'
    __table_args__ = STRICT

    id:           Mapped[int]        = mapped_column(primary_key=True, autoincrement=True)
    discord_id:   Mapped[str]        = mapped_column(unique=True)
    username:     Mapped[str]
    display_name: Mapped[str | None]
    is_admin:     Mapped[bool]       = mapped_column(default=False)
