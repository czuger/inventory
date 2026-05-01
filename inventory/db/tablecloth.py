from mongoengine import Document, StringField, ReferenceField

from .association import Association
from .category import Category
from .game import Game
from .tablecloth_size import TableclothSize
from .location import Location


class Tablecloth(Document):
    association = ReferenceField(Association, required=True)
    category = ReferenceField(Category, required=True)
    type = StringField(required=True)
    game = ReferenceField(Game, required=True)
    size = ReferenceField(TableclothSize, required=True)
    location = ReferenceField(Location, required=True)
    meta = {'collection': 'tablecoths'}
