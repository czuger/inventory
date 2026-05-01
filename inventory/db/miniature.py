from mongoengine import Document, StringField, IntField, ReferenceField

from .association import Association
from .category import Category
from .game import Game
from .scale import Scale
from .location import Location


class Miniature(Document):
    association = ReferenceField(Association, required=True)
    category = ReferenceField(Category, required=True)
    type = StringField(required=True)
    game = ReferenceField(Game, required=True)
    scale = ReferenceField(Scale, required=True)
    quantity = IntField(default=1)
    location = ReferenceField(Location, required=True)
    meta = {'collection': 'miniatures'}
