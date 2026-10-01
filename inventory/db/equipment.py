from sqlalchemy.orm import Mapped

from .base import db
from .item import ItemMixin, item_table_args


class Equipment(ItemMixin, db.Model):
    __tablename__ = 'equipment'
    __table_args__ = item_table_args()

    type: Mapped[str]
