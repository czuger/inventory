from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from inventory.db.book import Book
from inventory.db.constants import CATEGORIES
from inventory.db.location import Location
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('books', __name__, url_prefix='/books')


def _refs():
    return dict(
        categories=CATEGORIES,
        locations=Location.objects.filter(association=current_app.config['CURRENT_ASSOCIATION']),
    )


@bp.route('/')
def index():
    assoc = current_app.config['CURRENT_ASSOCIATION']
    items = Book.objects.filter(association=assoc)
    return render_template('book/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Book, id)
    return render_template('book/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Book(
            association=current_app.config['CURRENT_ASSOCIATION'],
            category=request.form['category'],
            name=request.form['name'],
            universe=request.form.get('universe', ''),
            period=request.form.get('period', ''),
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
        item.association = current_app.config['CURRENT_ASSOCIATION']
        item.category = request.form['category']
        item.name = request.form['name']
        item.universe = request.form.get('universe', '')
        item.period = request.form.get('period', '')
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
