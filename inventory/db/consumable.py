from mongoengine import Document, StringField, IntField, ReferenceField

from .association import Association
from .category import Category
from .location import Location


class Consumable(Document):
    association = ReferenceField(Association, required=True)
    category = ReferenceField(Category, required=True)
    type = StringField(required=True)
    unit = StringField()
    quantity = IntField(default=0)
    location = ReferenceField(Location, required=True)
    meta = {'collection': 'consumables'}
