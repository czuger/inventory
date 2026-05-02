from mongoengine import Document, IntField, ListField, ReferenceField, StringField

from .association import Association
from .location import Location


class Consumable(Document):
    association = ReferenceField(Association, required=True)
    category = StringField(required=True)
    type = StringField(required=True)
    unit = StringField()
    quantity = IntField(default=0)
    location = ReferenceField(Location, required=True)
    images = ListField(StringField(), default=list)

    meta = {'collection': 'consumables'}
