from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .association import Association
from .base import STRICT, db, utcnow


class DuplicateLink(db.Model):
    """An undirected "these two items may be the same" link: always query both ends.

    Like Borrowing, the (item_type, item_id) pairs cannot carry a foreign key.
    """
    __tablename__ = 'duplicate_links'
    __table_args__ = STRICT

    id:             Mapped[int]      = mapped_column(primary_key=True, autoincrement=True)
    association_id: Mapped[int]      = mapped_column(ForeignKey('associations.id'), index=True)
    item1_id:       Mapped[int]
    item1_type:     Mapped[str]
    item2_id:       Mapped[int]
    item2_type:     Mapped[str]
    created_at:     Mapped[datetime] = mapped_column(default=utcnow)

    association: Mapped[Association] = relationship()
