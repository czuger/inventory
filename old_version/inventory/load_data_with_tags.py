import json

from old_version.inventory.db.base import init_db, create_session
from old_version.inventory.db.items import Item, Location
from old_version.inventory.db.tags import Tag


def add_tag_if_not_exist(session, tag_name, item):
    """
    Add a tag to an item if it doesn't already exist in the database.

    Args:
        session: SQLAlchemy database session
        tag_name: Name of the tag to add
        item: Item object to which the tag should be added

    Returns:
        The Tag object that was created or retrieved
    """
    # Check if tag already exists
    tag = session.query(Tag).filter_by(name=tag_name).first()

    # If tag doesn't exist, create it
    if not tag:
        tag = Tag(name=tag_name)
        session.add(tag)
        session.flush()  # To get the ID

    # Add tag to the item if not already added
    if tag not in item.tags:
        item.tags.append(tag)

    return tag


def load_data_from_json(json_file_path, db_session):
    # Load JSON data
    with open(json_file_path, 'r', encoding='utf-8') as file:
        data = json.load(file)

    # Process each item in the data
    for item_data in data:
        if "name" not in item_data:
            continue
        # Extract the basic item information
        item = Item(name=item_data['name'])

        # Process location
        if 'location' in item_data and item_data['location']:
            # Check if location already exists
            location_name = item_data['location']
            location = db_session.query(Location).filter_by(name=location_name).first()

            if not location:
                # Create new location
                location = Location(name=location_name)
                db_session.add(location)
                db_session.flush()  # To get the ID

            # Associate location with item
            item.location = location

        # Add tags for all fields except name and location
        for field, value in item_data.items():
            # Skip name and location as they are handled separately
            if field in ['name', 'location']:
                continue

            if field == 'remarks' and value:
                # Split remarks into separate tags
                for remark in value.split(','):
                    remark = remark.strip()
                    if remark:
                        add_tag_if_not_exist(db_session, remark, item)
            elif value:  # Handle all other fields
                tag_name = f"{field}:{value}"
                add_tag_if_not_exist(db_session, tag_name, item)

        # Add the item to the session
        db_session.add(item)

    # Commit all changes
    db_session.commit()


def main():
    engine = init_db("../config/config.json")
    session = create_session(engine)

    load_data_from_json("../config/input.json", session)


if __name__ == "__main__":
    main()
