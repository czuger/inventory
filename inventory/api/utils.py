import io
import os
import uuid

from flask import abort, current_app, flash, g, redirect, request, send_file, url_for
from werkzeug.utils import secure_filename

from inventory.api.pdf import make_stickers_pdf
from inventory.db.association import Association
from inventory.db.borrowing import Borrowing
from inventory.libs.get_or_404 import get_or_404

_SLUG_TO_TYPE = {
    'miniatures':  'miniature',
    'terrains':    'terrain',
    'tablecloths': 'tablecloth',
    'rulebooks':   'rulebook',
    'board-games': 'board_game',
    'books':       'book',
    'equipment':   'equipment',
    'consumables': 'consumable',
}


def _parse_item_url(url_string):
    """Returns (item_type, item_id) parsed from an item URL, or (None, None)."""
    from urllib.parse import urlparse
    try:
        parts = [p for p in urlparse(url_string.strip()).path.split('/') if p]
        if len(parts) < 3:
            return None, None
        return _SLUG_TO_TYPE.get(parts[1]), parts[2]
    except Exception:
        return None, None


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
        if view in ('create', 'edit', 'delete', 'upload_image', 'delete_image', 'stickers'):
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


def register_borrow_routes(bp, item_type, Model):
    @bp.route('/<id>/borrow', methods=['POST'])
    def borrow(id):
        if not g.current_user:
            abort(401)
        Borrowing(
            association=g.assoc,
            borrower=g.current_user,
            item_id=id,
            item_type=item_type,
            action='borrow',
        ).save()
        item = get_or_404(Model, id)
        item.borrowing_count = (item.borrowing_count or 0) + 1
        item.save()
        return redirect(request.referrer)

    @bp.route('/<id>/return', methods=['POST'])
    def return_item(id):
        if not g.current_user:
            abort(401)
        Borrowing(
            association=g.assoc,
            borrower=g.current_user,
            item_id=id,
            item_type=item_type,
            action='return',
        ).save()
        item = get_or_404(Model, id)
        item.borrowing_count = max(0, (item.borrowing_count or 0) - 1)
        item.save()
        return redirect(request.referrer)


def register_duplicate_routes(bp, item_type, Model):
    from inventory.api.item_labels import get_item_display
    from inventory.db.duplicate_link import DuplicateLink

    @bp.route('/<id>/duplicates', methods=['POST'])
    def add_duplicate(id):
        if not (getattr(g, 'current_user', None) and g.current_user.is_admin):
            abort(403)
        item = get_or_404(Model, id)
        other_type, other_id = _parse_item_url(request.form.get('duplicate_url', ''))
        fallback = request.referrer or url_for(f'{request.blueprint}.show', id=id)
        if other_type is None or not other_id:
            flash('Invalid item URL.', 'danger')
            return redirect(fallback)
        if other_type == item_type and other_id == str(item.id):
            flash('Cannot link an item to itself.', 'warning')
            return redirect(fallback)
        existing = DuplicateLink.objects(association=g.assoc).filter(
            __raw__={'$or': [
                {'item1_id': str(item.id), 'item1_type': item_type,
                 'item2_id': other_id,     'item2_type': other_type},
                {'item1_id': other_id,     'item1_type': other_type,
                 'item2_id': str(item.id), 'item2_type': item_type},
            ]}
        ).first()
        if existing:
            flash('This link already exists.', 'warning')
            return redirect(fallback)
        label, _ = get_item_display(other_type, other_id)
        if label is None:
            flash('Linked item not found.', 'danger')
            return redirect(fallback)
        DuplicateLink(
            association=g.assoc,
            item1_id=str(item.id),
            item1_type=item_type,
            item2_id=other_id,
            item2_type=other_type,
        ).save()
        flash('Suspected duplicate link added.', 'success')
        return redirect(fallback)

    @bp.route('/<id>/duplicates/<link_id>/delete', methods=['POST'])
    def delete_duplicate(id, link_id):
        if not (getattr(g, 'current_user', None) and g.current_user.is_admin):
            abort(403)
        get_or_404(Model, id)
        link = DuplicateLink.objects(id=link_id).first()
        if link:
            link.delete()
            flash('Duplicate link removed.', 'success')
        return redirect(request.referrer or url_for(f'{request.blueprint}.show', id=id))


def register_sticker_routes(bp, Model, get_lines):
    @bp.route('/stickers')
    def stickers():
        items = list(Model.objects.filter(association=g.assoc))
        data = [(get_lines(item), url_for(request.blueprint + '.show', id=item.id, _external=True))
                for item in items]
        pdf_bytes = make_stickers_pdf(data)
        for item in items:
            item.sticker_printed = True
            item.save()
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=False,
            download_name='stickers.pdf',
        )
