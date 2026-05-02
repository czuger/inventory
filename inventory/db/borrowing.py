from datetime import datetime

from mongoengine import DateTimeField, Document, ReferenceField, StringField

from inventory.db.association import Association
from inventory.db.user import User


class Borrowing(Document):
    association = ReferenceField(Association, required=True)
    borrower    = ReferenceField(User, required=True)
    item_id     = StringField(required=True)
    item_type   = StringField(required=True)
    action      = StringField(required=True, choices=['borrow', 'return'])
    date        = DateTimeField(required=True, default=datetime.utcnow)

    meta = {'collection': 'borrowings', 'ordering': ['-date']}
