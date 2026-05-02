from mongoengine import Document, StringField, IntField, ReferenceField

from .association import Association
from .game import Game
from .location import Location


class Miniature(Document):
    association = ReferenceField(Association, required=True)
    category = StringField(required=True)
    type = StringField(required=True)
    game = ReferenceField(Game, required=True)
    scale = StringField(required=True)
    quantity = IntField(default=1)
    location = ReferenceField(Location, required=True)
    meta = {'collection': 'miniatures'}
