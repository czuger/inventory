from mongoengine import Document, StringField


class TableclothSize(Document):
    size_cm = StringField(required=True, unique=True)
    size_inches = StringField(required=True, unique=True)
    meta = {'collection': 'tablecloth_sizes'}
