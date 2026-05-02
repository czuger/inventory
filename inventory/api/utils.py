from flask import abort, current_app, g, request

from inventory.db.association import Association


def register_assoc_hooks(bp):
    @bp.url_value_preprocessor
    def pull_assoc(endpoint, values):
        assoc = Association.objects(slug=values.pop('slug', None)).first()
        if assoc is None:
            abort(404)
        g.assoc = assoc

    @bp.url_defaults
    def inject_slug(endpoint, values):
        if 'slug' not in values and hasattr(g, 'assoc'):
            values['slug'] = g.assoc.slug

    @bp.before_request
    def check_admin():
        view = (request.endpoint or '').rsplit('.', 1)[-1]
        if view in ('create', 'edit', 'delete') and not current_app.config.get('ADMIN'):
            abort(403)
