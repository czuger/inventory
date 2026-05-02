from mongoengine import BooleanField, Document, StringField


class User(Document):
    discord_id   = StringField(required=True, unique=True)
    username     = StringField(required=True)
    display_name = StringField()
    is_admin     = BooleanField(default=False)
    meta = {'collection': 'users'}
