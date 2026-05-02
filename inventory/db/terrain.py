from mongoengine import Document, IntField, ListField, ReferenceField, StringField

from .association import Association
from .game import Game
from .location import Location


class Terrain(Document):
    association = ReferenceField(Association, required=True)
    category = StringField(required=True)
    type = StringField(required=True)
    game = ReferenceField(Game, required=True)
    scale = StringField(required=True)
    theater = StringField()
    quantity = IntField(default=1)
    location = ReferenceField(Location, required=True)
    images = ListField(StringField(), default=list)

    meta = {'collection': 'terrains'}
