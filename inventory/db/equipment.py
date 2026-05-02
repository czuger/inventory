from mongoengine import Document, IntField, ListField, ReferenceField, StringField

from .association import Association
from .location import Location


class Equipment(Document):
    association = ReferenceField(Association, required=True)
    category = StringField(required=True)
    type = StringField(required=True)
    quantity        = IntField(default=1)
    borrowing_count = IntField(default=0)
    location = ReferenceField(Location, required=True)
    images = ListField(StringField(), default=list)

    meta = {'collection': 'equipment'}
