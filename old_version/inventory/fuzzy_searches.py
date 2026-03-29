from sqlalchemy import func, or_, select, cast, column, String
from sqlalchemy.orm import create_session

from old_version.inventory.db.base import init_db
from old_version.inventory.db.tags import ItemTag, Location


def fuzzy_search(session, search_term, limit=20, similarity_threshold=0.3):
    """
    Perform fuzzy search across ItemTag objects using name and tags

    Args:
        session: SQLAlchemy session
        search_term: The term to search for
        limit: Maximum number of results to return
        similarity_threshold: Minimum similarity score (0-1)

    Returns:
        List of tuples (ItemTag, similarity_score)
    """
    search_term = search_term.lower()

    # Calculate similarity between search term and name
    name_sim = func.similarity(ItemTag.name, search_term)

    # This is the modified approach without using unnest
    # We'll use PostgreSQL's array operators to find matches within the tags array

    # Build the query
    query = (
        select(ItemTag, name_sim.label('similarity'))
        .join(Location, ItemTag.location_id == Location.id, isouter=True)
        .where(
            or_(
                # Direct trigram similarity search on name
                name_sim > similarity_threshold,

                # Check if any tag contains the search term (exact match)
                ItemTag.tags.op('@>')(func.array([search_term])),

                # Check if any tag contains a substring of the search term
                # This uses PostgreSQL's "array overlap with LIKE pattern" operator
                ItemTag.tags.any(func.lower(cast(column("x"), String)).like(f"%{search_term}%"))
            )
        )
        .order_by(name_sim.desc())
        .limit(limit)
    )

    # Execute and return results
    return session.execute(query).all()


def main():
    engine = init_db("../config/config.json")
    session = create_session(engine)

    for e in fuzzy_search(session, "saga"):
        print(e, e[0].category, e[0].subcategory, e[0].location)


if __name__ == "__main__":
    main()
