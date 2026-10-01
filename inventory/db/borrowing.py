from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .association import Association
from .base import STRICT, db, utcnow
from .user import User


class Borrowing(db.Model):
    """One borrow or return event; an item's status is its latest event.

    (item_type, item_id) points into one of the eight item tables, so no foreign
    key can guard it: deleting an item leaves its events behind, as it always has.
    """
    __tablename__ = 'borrowings'
    __table_args__ = (
        CheckConstraint("action IN ('borrow', 'return')", name='action_choices'),
        Index('ix_borrowings_item', 'item_type', 'item_id', 'date'),
        STRICT,
    )

    id:             Mapped[int]      = mapped_column(primary_key=True, autoincrement=True)
    association_id: Mapped[int]      = mapped_column(ForeignKey('associations.id'))
    borrower_id:    Mapped[int]      = mapped_column(ForeignKey('users.id'))
    item_id:        Mapped[int]
    item_type:      Mapped[str]
    action:         Mapped[str]
    date:           Mapped[datetime] = mapped_column(default=utcnow)

    association: Mapped[Association] = relationship()
    borrower:    Mapped[User]        = relationship()
