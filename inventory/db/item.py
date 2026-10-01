from sqlalchemy import JSON, CheckConstraint, ForeignKey
from sqlalchemy.ext.mutable import MutableList
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship

from .association import Association
from .base import STRICT
from .location import Location


def item_table_args(*constraints):
    """`__table_args__` for an item table: its own constraints plus the shared ones."""
    return (
        # `images` is JSON text in a TEXT column, so STRICT alone would accept any
        # string; this keeps it a JSON array.
        CheckConstraint("json_type(images) = 'array'", name='images_is_array'),
        *constraints,
        STRICT,
    )


class ItemMixin:
    """The columns all eight item types share; each model adds its few own fields."""

    # sort_order only puts these first in CREATE TABLE, ahead of the type's own fields.
    id:              Mapped[int]  = mapped_column(primary_key=True, autoincrement=True, sort_order=-1)
    association_id:  Mapped[int]  = mapped_column(ForeignKey('associations.id'), index=True, sort_order=-1)
    category:        Mapped[str]  = mapped_column(sort_order=-1)
    quantity:        Mapped[int]  = mapped_column(default=1)
    borrowing_count: Mapped[int]  = mapped_column(default=0)
    sticker_printed: Mapped[bool] = mapped_column(default=False)
    location_id:     Mapped[int]  = mapped_column(ForeignKey('locations.id'))
    # Filenames under uploads/<category>/<id>/, in upload order. A JSON list rather
    # than a child table: it is only ever read and rewritten whole, per item, and a
    # table would need one copy per item type. MutableList makes in-place
    # .append()/.remove() mark the row dirty.
    images:          Mapped[list[str]] = mapped_column(MutableList.as_mutable(JSON), default=list)

    @declared_attr
    def association(cls) -> Mapped[Association]:
        return relationship()

    # Joined: every list and show page prints the location of every item.
    @declared_attr
    def location(cls) -> Mapped[Location]:
        return relationship(lazy='joined')
