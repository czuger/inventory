from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from inventory.db.constants import CATEGORIES
from inventory.db.consumable import Consumable
from inventory.db.location import Location
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('consumables', __name__, url_prefix='/consumables')


def _refs():
    return dict(
        categories=CATEGORIES,
        locations=Location.objects.filter(association=current_app.config['CURRENT_ASSOCIATION']),
    )


@bp.route('/')
def index():
    assoc = current_app.config['CURRENT_ASSOCIATION']
    items = Consumable.objects.filter(association=assoc)
    return render_template('consumable/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Consumable, id)
    return render_template('consumable/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Consumable(
            association=current_app.config['CURRENT_ASSOCIATION'],
            category=request.form['category'],
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
        item.association = current_app.config['CURRENT_ASSOCIATION']
        item.category = request.form['category']
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
