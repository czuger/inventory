from sqlalchemy.orm import Mapped, mapped_column

from .base import db
from .item import ItemMixin, item_table_args


class Consumable(ItemMixin, db.Model):
    __tablename__ = 'consumables'
    __table_args__ = item_table_args()

    type:     Mapped[str]
    unit:     Mapped[str | None]
    # Unlike every other item type, a consumable starts at 0.
    quantity: Mapped[int] = mapped_column(default=0)
