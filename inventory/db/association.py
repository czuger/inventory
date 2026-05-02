from mongoengine import Document, StringField


class Association(Document):
    name = StringField(required=True, unique=True)
    slug = StringField(required=True, unique=True)
    meta = {'collection': 'associations'}
