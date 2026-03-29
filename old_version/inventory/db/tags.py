from sqlalchemy import Column, Integer, String, ForeignKey, Table
from sqlalchemy.orm import relationship

from old_version.inventory.db.base import Base

item_tag = Table(
    'item_tag',
    Base.metadata,
    Column('item_id', Integer, ForeignKey('items.id'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id'), primary_key=True)
)


# Tag model
class Tag(Base):
    __tablename__ = 'tags'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)

    # Relationship with items
    items = relationship("Item", secondary=item_tag, back_populates="tags")

    def __repr__(self):
        return f"<Tag(name='{self.name}')>"
