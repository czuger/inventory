from flask import Blueprint, flash, redirect, render_template, request, url_for

from inventory.db.association import Association
from inventory.db.category import Category
from inventory.db.consumable import Consumable
from inventory.db.location import Location
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('consumables', __name__, url_prefix='/consumables')


def _refs():
    return dict(
        associations=Association.objects.order_by('name'),
        categories=Category.objects.order_by('name'),
        locations=Location.objects.all(),
    )


@bp.route('/')
def index():
    items = Consumable.objects.all()
    return render_template('consumable/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Consumable, id)
    return render_template('consumable/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Consumable(
            association=Association.objects.get(id=request.form['association']),
            category=Category.objects.get(id=request.form['category']),
            type=request.form['type'],
            unit=request.form.get('unit', ''),
            quantity=int(request.form.get('quantity') or 0),
            location=Location.objects.get(id=request.form['location']),
        )
        item.save()
        flash('Consumable created.', 'success')
        return redirect(url_for('consumables.show', id=item.id))
    return render_template('consumable/form.html', obj=None, action=url_for('consumables.create'), **_refs())


@bp.route('/<id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = get_or_404(Consumable, id)
    if request.method == 'POST':
        item.association = Association.objects.get(id=request.form['association'])
        item.category = Category.objects.get(id=request.form['category'])
        item.type = request.form['type']
        item.unit = request.form.get('unit', '')
        item.quantity = int(request.form.get('quantity') or 0)
        item.location = Location.objects.get(id=request.form['location'])
        item.save()
        flash('Consumable updated.', 'success')
        return redirect(url_for('consumables.show', id=item.id))
    return render_template('consumable/form.html', obj=item, action=url_for('consumables.edit', id=item.id), **_refs())


@bp.route('/<id>/delete', methods=['POST'])
def delete(id):
    item = get_or_404(Consumable, id)
    item.delete()
    flash('Consumable deleted.', 'success')
    return redirect(url_for('consumables.index'))
