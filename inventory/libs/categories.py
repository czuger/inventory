from mongoengine import Document, StringField, ListField


class Category(Document):
    category = StringField(required=True, unique=True)
    sub_categories = ListField(StringField())

    meta = {"collection": "categories"}
