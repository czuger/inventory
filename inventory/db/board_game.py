from mongoengine import Document, ListField, ReferenceField, StringField

from .association import Association
from .location import Location


class BoardGame(Document):
    association = ReferenceField(Association, required=True)
    category = StringField(required=True)
    name = StringField(required=True)
    universe = StringField()
    location = ReferenceField(Location, required=True)
    images = ListField(StringField(), default=list)

    meta = {'collection': 'board_games'}
