from flask import abort, g

from inventory.db.base import db


def get_or_404(model: type, object_id: int | str) -> object:
    """Retrieve a row by primary key or abort with 404.

    Rows that belong to an association are only found within the current one
    (`g.assoc`), so an id from another association's URL is a 404 too.

    Args:
        model: The SQLAlchemy model class to query.
        object_id: The id of the row, as an int or as a string from a form.

    Returns:
        The found row.
    """
    try:
        object_id = int(object_id)
    except (TypeError, ValueError):
        abort(404)
    obj = db.session.get(model, object_id)
    if obj is None:
        abort(404)
    assoc = getattr(g, 'assoc', None)
    if assoc is not None and getattr(obj, 'association_id', assoc.id) != assoc.id:
        abort(404)
    return obj
