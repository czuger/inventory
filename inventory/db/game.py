from sqlalchemy.orm import Mapped, mapped_column

from .base import STRICT, db


class Game(db.Model):
    __tablename__ = 'games'
    __table_args__ = STRICT

    id:   Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True)
