from sqlalchemy.orm import Mapped, mapped_column

from .base import db


class LegacyObjectId(db.Model):
    """MongoDB ObjectId -> integer id of every item imported from MongoDB.

    Written once by misc/migrate_mongo_to_sqlite.py and only read afterwards. It
    exists for the stickers already on the shelves: their QR codes encode
    /<slug>/<items>/<ObjectId>, and the app redirects those to the new URL.
    """
    __tablename__ = 'legacy_object_ids'
    # STRICT only: autoincrement applies to integer keys, and this one is the ObjectId.
    __table_args__ = {'sqlite_strict': True}

    object_id: Mapped[str] = mapped_column(primary_key=True)
    item_type: Mapped[str]
    item_id:   Mapped[int]
