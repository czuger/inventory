from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import db
from .game import Game
from .item import ItemMixin, item_table_args

TABLECLOTH_MATERIALS = ["mousepad (neoprene)", "vinyl", "cloth", "textured"]


class Tablecloth(ItemMixin, db.Model):
    __tablename__ = 'tablecloths'
    __table_args__ = item_table_args(
        CheckConstraint(
            'material IN (' + ', '.join(f"'{m}'" for m in TABLECLOTH_MATERIALS) + ')',
            name='material_choices',
        ),
    )

    type:     Mapped[str]
    material: Mapped[str | None]
    game_id:  Mapped[int] = mapped_column(ForeignKey('games.id'))
    size:     Mapped[str]
    remarks:  Mapped[str | None]

    game: Mapped[Game] = relationship(lazy='joined')
