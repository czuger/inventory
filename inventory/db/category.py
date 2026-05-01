from mongoengine import Document, StringField


class Category(Document):
    name = StringField(required=True, unique=True)
    meta = {'collection': 'categories'}
