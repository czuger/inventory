from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .association import Association
from .base import STRICT, db


class Location(db.Model):
    __tablename__ = 'locations'
    # `spot` is '' rather than NULL when there is none: SQL treats NULLs as distinct
    # in a unique constraint, so (assoc, room, NULL) could be inserted twice, where
    # MongoDB's unique index allowed it only once.
    __table_args__ = (UniqueConstraint('association_id', 'room', 'spot'), STRICT)

    id:             Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    association_id: Mapped[int] = mapped_column(ForeignKey('associations.id'))
    room:           Mapped[str]
    spot:           Mapped[str] = mapped_column(default='')

    association: Mapped[Association] = relationship()
