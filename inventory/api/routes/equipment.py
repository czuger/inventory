from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from inventory.db.constants import CATEGORIES
from inventory.db.equipment import Equipment
from inventory.db.location import Location
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('equipment', __name__, url_prefix='/equipment')


def _refs():
    return dict(
        categories=CATEGORIES,
        locations=Location.objects.filter(association=current_app.config['CURRENT_ASSOCIATION']),
    )


@bp.route('/')
def index():
    assoc = current_app.config['CURRENT_ASSOCIATION']
    items = Equipment.objects.filter(association=assoc)
    return render_template('equipment/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Equipment, id)
    return render_template('equipment/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Equipment(
            association=current_app.config['CURRENT_ASSOCIATION'],
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
        item.association = current_app.config['CURRENT_ASSOCIATION']
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
