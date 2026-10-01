from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select

from inventory.api.item_labels import get_sticker_lines
from inventory.api.utils import register_assoc_hooks, register_borrow_routes, register_duplicate_routes, register_image_routes, register_sticker_routes
from inventory.db.book import Book
from inventory.db.base import db
from inventory.db.constants import CATEGORIES
from inventory.db.location import Location
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('books', __name__, url_prefix='/<slug>/books')
register_assoc_hooks(bp)
register_image_routes(bp, Book)
register_borrow_routes(bp, 'book', Book)
register_duplicate_routes(bp, 'book', Book)
register_sticker_routes(bp, Book, lambda item: get_sticker_lines('book', item))


def _refs():
    return dict(
        default_category='Book',
        categories=CATEGORIES,
        locations=db.session.scalars(select(Location).filter_by(association=g.assoc)).all(),
    )


@bp.route('/')
def index():
    items = db.session.scalars(select(Book).filter_by(association=g.assoc)).all()
    return render_template('book/list.html', items=items)


@bp.route('/<int:id>')
def show(id):
    item = get_or_404(Book, id)
    return render_template('book/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Book(
            association=g.assoc,
            category=request.form['category'],
            name=request.form['name'],
            universe=request.form.get('universe', ''),
            period=request.form.get('period', ''),
            quantity=int(request.form.get('quantity') or 1),
            location=get_or_404(Location, request.form['location']),
        )
        db.session.add(item)
        db.session.commit()
        flash('Book created.', 'success')
        return redirect(url_for('books.show', id=item.id))
    return render_template('book/form.html', obj=None, action=url_for('books.create'), **_refs())


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = get_or_404(Book, id)
    if request.method == 'POST':
        item.association = g.assoc
        item.category = request.form['category']
        item.name = request.form['name']
        item.universe = request.form.get('universe', '')
        item.period = request.form.get('period', '')
        item.quantity = int(request.form.get('quantity') or 1)
        item.location = get_or_404(Location, request.form['location'])
        item.sticker_printed = 'sticker_printed' in request.form
        db.session.commit()
        flash('Book updated.', 'success')
        return redirect(url_for('books.show', id=item.id))
    return render_template('book/form.html', obj=item, action=url_for('books.edit', id=item.id), **_refs())


@bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    item = get_or_404(Book, id)
    db.session.delete(item)
    db.session.commit()
    flash('Book deleted.', 'success')
    return redirect(url_for('books.index'))
