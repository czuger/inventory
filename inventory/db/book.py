from sqlalchemy.orm import Mapped

from .base import db
from .item import ItemMixin, item_table_args


class Book(ItemMixin, db.Model):
    __tablename__ = 'books'
    __table_args__ = item_table_args()

    name:     Mapped[str]
    universe: Mapped[str | None]
    period:   Mapped[str | None]
