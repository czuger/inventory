from datetime import datetime

from mongoengine import DateTimeField, Document, ReferenceField, StringField

from inventory.db.association import Association


class DuplicateLink(Document):
    association = ReferenceField(Association, required=True)
    item1_id    = StringField(required=True)
    item1_type  = StringField(required=True)
    item2_id    = StringField(required=True)
    item2_type  = StringField(required=True)
    created_at  = DateTimeField(required=True, default=datetime.utcnow)

    meta = {'collection': 'duplicate_links'}
