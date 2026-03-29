from flask import abort


def get_or_404(model: object, object_id: str) -> object:
    """Retrieve a MongoDB document by ID or abort with 404.

    Args:
        model: The MongoEngine model class to query.
        object_id: The ID of the document to retrieve.

    Returns:
        The found document.
    """
    obj = model.objects(id=object_id).first()
    if not obj:
        abort(404)
    return obj
