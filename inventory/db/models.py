"""Imports every model, so that `db.metadata` is complete.

Alembic's env.py and the test suite rely on this: a model that is not imported
here is invisible to autogenerate, which would then propose dropping its table.
"""
from .association import Association
from .board_game import BoardGame
from .book import Book
from .borrowing import Borrowing
from .consumable import Consumable
from .duplicate_link import DuplicateLink
from .equipment import Equipment
from .game import Game
from .legacy_object_id import LegacyObjectId
from .location import Location
from .miniature import Miniature
from .rulebook import Rulebook
from .tablecloth import Tablecloth
from .terrain import Terrain
from .user import User

__all__ = [
    'Association', 'BoardGame', 'Book', 'Borrowing', 'Consumable', 'DuplicateLink',
    'Equipment', 'Game', 'LegacyObjectId', 'Location', 'Miniature', 'Rulebook',
    'Tablecloth', 'Terrain', 'User',
]
