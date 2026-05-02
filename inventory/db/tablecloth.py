from mongoengine import Document, IntField, ListField, ReferenceField, StringField

from .association import Association
from .game import Game
from .location import Location

TABLECLOTH_MATERIALS = ["mousepad (neoprene)", "vinyl", "cloth", "textured"]


class Tablecloth(Document):
    association = ReferenceField(Association, required=True)
    category = StringField(required=True)
    quantity = IntField(default=1)
    type = StringField(required=True)
    material = StringField(choices=TABLECLOTH_MATERIALS)
    game = ReferenceField(Game, required=True)
    size = StringField(required=True)
    remarks = StringField()
    location = ReferenceField(Location, required=True)
    images = ListField(StringField(), default=list)

    meta = {'collection': 'tablecoths'}
