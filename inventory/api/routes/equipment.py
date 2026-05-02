from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from inventory.api.utils import register_assoc_hooks, register_image_routes
from inventory.db.constants import CATEGORIES
from inventory.db.equipment import Equipment
from inventory.db.location import Location
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('equipment', __name__, url_prefix='/<slug>/equipment')
register_assoc_hooks(bp)
register_image_routes(bp, Equipment)


def _refs():
    return dict(
        default_category='Equipment',
        categories=CATEGORIES,
        locations=Location.objects.filter(association=g.assoc),
    )


@bp.route('/')
def index():
    items = Equipment.objects.filter(association=g.assoc)
    return render_template('equipment/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Equipment, id)
    return render_template('equipment/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Equipment(
            association=g.assoc,
            category=request.form['category'],
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
        item.association = g.assoc
        item.category = request.form['category']
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
