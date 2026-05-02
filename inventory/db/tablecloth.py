from mongoengine import Document, IntField, StringField, ReferenceField

from .association import Association
from .category import Category
from .game import Game
from .tablecloth_size import TableclothSize
from .location import Location


TABLECLOTH_MATERIALS = ["mousepad (neoprene)", "vinyl", "cloth", "textured"]


class Tablecloth(Document):
    association = ReferenceField(Association, required=True)
    category = ReferenceField(Category, required=True)
    number = IntField()
    type = StringField(required=True)
    material = StringField(choices=TABLECLOTH_MATERIALS)
    game = ReferenceField(Game, required=True)
    size = ReferenceField(TableclothSize, required=True)
    remarks = StringField()
    location = ReferenceField(Location, required=True)
    meta = {'collection': 'tablecoths'}
