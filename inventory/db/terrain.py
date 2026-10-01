from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import db
from .game import Game
from .item import ItemMixin, item_table_args


class Terrain(ItemMixin, db.Model):
    __tablename__ = 'terrains'
    __table_args__ = item_table_args()

    type:    Mapped[str]
    game_id: Mapped[int] = mapped_column(ForeignKey('games.id'))
    scale:   Mapped[str]
    theater: Mapped[str | None]

    game: Mapped[Game] = relationship(lazy='joined')
