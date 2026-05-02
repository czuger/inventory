from mongoengine import Document, StringField, IntField, ReferenceField

from .association import Association
from .location import Location


class Equipment(Document):
    association = ReferenceField(Association, required=True)
    category = StringField(required=True)
    type = StringField(required=True)
    quantity = IntField(default=1)
    location = ReferenceField(Location, required=True)
    meta = {'collection': 'equipment'}
