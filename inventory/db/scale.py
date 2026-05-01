from mongoengine import Document, StringField


class Scale(Document):
    value = StringField(required=True, unique=True)
    meta = {'collection': 'scales'}
