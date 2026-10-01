from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import db
from .game import Game
from .item import ItemMixin, item_table_args


class Rulebook(ItemMixin, db.Model):
    __tablename__ = 'rulebooks'
    __table_args__ = item_table_args()

    name:       Mapped[str]
    game_id:    Mapped[int]  = mapped_column(ForeignKey('games.id'))
    supplement: Mapped[bool] = mapped_column(default=False)

    game: Mapped[Game] = relationship(lazy='joined')
