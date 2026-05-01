from mongoengine import Document, StringField, ReferenceField

from .association import Association


class Location(Document):
    association = ReferenceField(Association, required=True)
    room = StringField(required=True)
    spot = StringField()
    meta = {
        'collection': 'locations',
        'indexes': [
            {'fields': ('association', 'room', 'spot'), 'unique': True}
        ]
    }
