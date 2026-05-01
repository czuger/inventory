from mongoengine import Document, StringField, ReferenceField

from .association import Association
from .category import Category
from .location import Location


class Book(Document):
    association = ReferenceField(Association, required=True)
    category = ReferenceField(Category, required=True)
    name = StringField(required=True)
    universe = StringField()
    period = StringField()
    location = ReferenceField(Location, required=True)
    meta = {'collection': 'books'}
