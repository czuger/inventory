from mongoengine import Document, StringField


class Game(Document):
    name = StringField(required=True, unique=True)
    meta = {'collection': 'games'}
