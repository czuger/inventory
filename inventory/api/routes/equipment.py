from flask import Blueprint, flash, redirect, render_template, request, url_for

from inventory.db.association import Association
from inventory.db.category import Category
from inventory.db.equipment import Equipment
from inventory.db.location import Location
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('equipment', __name__, url_prefix='/equipment')


def _refs():
    return dict(
        associations=Association.objects.order_by('name'),
        categories=Category.objects.order_by('name'),
        locations=Location.objects.all(),
    )


@bp.route('/')
def index():
    items = Equipment.objects.all()
    return render_template('equipment/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Equipment, id)
    return render_template('equipment/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Equipment(
            association=Association.objects.get(id=request.form['association']),
            category=Category.objects.get(id=request.form['category']),
            type=request.form['type'],
            quantity=int(request.form.get('quantity') or 1),
            location=Location.objects.get(id=request.form['location']),
        )
        item.save()
        flash('Equipment created.', 'success')
        return redirect(url_for('equipment.show', id=item.id))
    return render_template('equipment/form.html', obj=None, action=url_for('equipment.create'), **_refs())


@bp.route('/<id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = get_or_404(Equipment, id)
    if request.method == 'POST':
        item.association = Association.objects.get(id=request.form['association'])
        item.category = Category.objects.get(id=request.form['category'])
        item.type = request.form['type']
        item.quantity = int(request.form.get('quantity') or 1)
        item.location = Location.objects.get(id=request.form['location'])
        item.save()
        flash('Equipment updated.', 'success')
        return redirect(url_for('equipment.show', id=item.id))
    return render_template('equipment/form.html', obj=item, action=url_for('equipment.edit', id=item.id), **_refs())


@bp.route('/<id>/delete', methods=['POST'])
def delete(id):
    item = get_or_404(Equipment, id)
    item.delete()
    flash('Equipment deleted.', 'success')
    return redirect(url_for('equipment.index'))
