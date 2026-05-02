from mongoengine import BooleanField, Document, IntField, ListField, ReferenceField, StringField

from .association import Association
from .game import Game
from .location import Location


class Miniature(Document):
    association = ReferenceField(Association, required=True)
    category = StringField(required=True)
    type = StringField(required=True)
    game = ReferenceField(Game, required=True)
    scale = StringField(required=True)
    quantity        = IntField(default=1)
    borrowing_count = IntField(default=0)
    sticker_printed = BooleanField(default=False)
    location = ReferenceField(Location, required=True)
    images = ListField(StringField(), default=list)

    meta = {'collection': 'miniatures'}
