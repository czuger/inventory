from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from inventory.api.utils import register_assoc_hooks, register_borrow_routes, register_image_routes, register_sticker_routes
from inventory.db.book import Book
from inventory.db.constants import CATEGORIES
from inventory.db.location import Location
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('books', __name__, url_prefix='/<slug>/books')
register_assoc_hooks(bp)
register_image_routes(bp, Book)
register_borrow_routes(bp, 'book', Book)
register_sticker_routes(bp, Book, lambda item: [
    item.name,
    *([item.universe] if item.universe else []),
    *([item.period] if item.period else []),
    f"Qté : {item.quantity}",
    f"{item.location.room}{' – ' + item.location.spot if item.location.spot else ''}",
])


def _refs():
    return dict(
        default_category='Book',
        categories=CATEGORIES,
        locations=Location.objects.filter(association=g.assoc),
    )


@bp.route('/')
def index():
    items = Book.objects.filter(association=g.assoc)
    return render_template('book/list.html', items=items)


@bp.route('/<id>')
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
            location=Location.objects.get(id=request.form['location']),
        )
        item.save()
        flash('Book created.', 'success')
        return redirect(url_for('books.show', id=item.id))
    return render_template('book/form.html', obj=None, action=url_for('books.create'), **_refs())


@bp.route('/<id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = get_or_404(Book, id)
    if request.method == 'POST':
        item.association = g.assoc
        item.category = request.form['category']
        item.name = request.form['name']
        item.universe = request.form.get('universe', '')
        item.period = request.form.get('period', '')
        item.quantity = int(request.form.get('quantity') or 1)
        item.location = Location.objects.get(id=request.form['location'])
        item.save()
        flash('Book updated.', 'success')
        return redirect(url_for('books.show', id=item.id))
    return render_template('book/form.html', obj=item, action=url_for('books.edit', id=item.id), **_refs())


@bp.route('/<id>/delete', methods=['POST'])
def delete(id):
    item = get_or_404(Book, id)
    item.delete()
    flash('Book deleted.', 'success')
    return redirect(url_for('books.index'))
