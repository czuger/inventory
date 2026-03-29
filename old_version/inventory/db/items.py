from sqlalchemy import Column, Integer, String, ForeignKey, Text
from sqlalchemy.orm import relationship

from old_version.inventory.db.base import Base
from old_version.inventory.db.tags import item_tag


class Location(Base):
    __tablename__ = 'locations'

    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

    # Relations
    items = relationship("Item", back_populates="location")

    def __repr__(self):
        return f"<Location(name='{self.name}')>"


class Item(Base):
    __tablename__ = 'items'

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    quantity = Column(String, nullable=True)
    remarks = Column(Text, nullable=True)

    # Foreign keys

    location_id = Column(Integer, ForeignKey('locations.id'), nullable=True)

    # Relations
    location = relationship("Location", back_populates="items")

    tags = relationship("Tag", secondary=item_tag, back_populates="items")

    def __repr__(self):
        return f"<Item(name='{self.name}', quantity='{self.quantity}')>"
