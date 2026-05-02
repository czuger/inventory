from mongoengine import BooleanField, Document, IntField, ListField, ReferenceField, StringField

from .association import Association
from .game import Game
from .location import Location


class Rulebook(Document):
    association = ReferenceField(Association, required=True)
    category = StringField(required=True)
    name = StringField(required=True)
    game = ReferenceField(Game, required=True)
    supplement = BooleanField(default=False)
    quantity = IntField(default=1)
    location = ReferenceField(Location, required=True)
    images = ListField(StringField(), default=list)

    meta = {'collection': 'rulebooks'}
