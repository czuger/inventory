import os
import uuid

from flask import abort, current_app, g, redirect, request
from werkzeug.utils import secure_filename

from inventory.db.association import Association
from inventory.libs.get_or_404 import get_or_404


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
        if view in ('create', 'edit', 'delete', 'upload_image', 'delete_image'):
            current_user = getattr(g, 'current_user', None)
            if not (current_user and current_user.is_admin):
                abort(403)


def register_image_routes(bp, Model):
    @bp.route('/<id>/images', methods=['POST'])
    def upload_image(id):
        item = get_or_404(Model, id)
        category_snake = item.category.lower().replace(' ', '_')
        upload_dir = os.path.join(current_app.static_folder, 'uploads', category_snake, str(item.id))
        os.makedirs(upload_dir, exist_ok=True)
        for f in request.files.getlist('images'):
            if f and f.filename:
                filename = str(uuid.uuid4()) + '_' + secure_filename(f.filename)
                f.save(os.path.join(upload_dir, filename))
                item.images.append(filename)
        item.save()
        return redirect(request.referrer)

    @bp.route('/<id>/images/<filename>/delete', methods=['POST'])
    def delete_image(id, filename):
        item = get_or_404(Model, id)
        if filename in item.images:
            category_snake = item.category.lower().replace(' ', '_')
            path = os.path.join(current_app.static_folder, 'uploads', category_snake, str(item.id), filename)
            if os.path.exists(path):
                os.remove(path)
            item.images.remove(filename)
            item.save()
        return redirect(request.referrer)
