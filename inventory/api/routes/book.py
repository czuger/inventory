from flask import Blueprint, flash, redirect, render_template, request, url_for

from inventory.db.association import Association
from inventory.db.book import Book
from inventory.db.category import Category
from inventory.db.location import Location
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('books', __name__, url_prefix='/books')


def _refs():
    return dict(
        associations=Association.objects.order_by('name'),
        categories=Category.objects.order_by('name'),
        locations=Location.objects.all(),
    )


@bp.route('/')
def index():
    items = Book.objects.all()
    return render_template('book/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Book, id)
    return render_template('book/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Book(
            association=Association.objects.get(id=request.form['association']),
            category=Category.objects.get(id=request.form['category']),
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
        item.association = Association.objects.get(id=request.form['association'])
        item.category = Category.objects.get(id=request.form['category'])
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
