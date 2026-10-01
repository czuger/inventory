from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select

from inventory.api.item_labels import get_sticker_lines
from inventory.api.utils import register_assoc_hooks, register_borrow_routes, register_duplicate_routes, register_image_routes, register_sticker_routes
from inventory.db.base import db
from inventory.db.constants import CATEGORIES
from inventory.db.consumable import Consumable
from inventory.db.location import Location
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('consumables', __name__, url_prefix='/<slug>/consumables')
register_assoc_hooks(bp)
register_image_routes(bp, Consumable)
register_borrow_routes(bp, 'consumable', Consumable)
register_duplicate_routes(bp, 'consumable', Consumable)
register_sticker_routes(bp, Consumable, lambda item: get_sticker_lines('consumable', item))


def _refs():
    return dict(
        default_category='Consumable',
        categories=CATEGORIES,
        locations=db.session.scalars(select(Location).filter_by(association=g.assoc)).all(),
    )


@bp.route('/')
def index():
    items = db.session.scalars(select(Consumable).filter_by(association=g.assoc)).all()
    return render_template('consumable/list.html', items=items)


@bp.route('/<int:id>')
def show(id):
    item = get_or_404(Consumable, id)
    return render_template('consumable/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Consumable(
            association=g.assoc,
            category=request.form['category'],
            type=request.form['type'],
            unit=request.form.get('unit', ''),
            quantity=int(request.form.get('quantity') or 0),
            location=get_or_404(Location, request.form['location']),
        )
        db.session.add(item)
        db.session.commit()
        flash('Consumable created.', 'success')
        return redirect(url_for('consumables.show', id=item.id))
    return render_template('consumable/form.html', obj=None, action=url_for('consumables.create'), **_refs())


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = get_or_404(Consumable, id)
    if request.method == 'POST':
        item.association = g.assoc
        item.category = request.form['category']
        item.type = request.form['type']
        item.unit = request.form.get('unit', '')
        item.quantity = int(request.form.get('quantity') or 0)
        item.location = get_or_404(Location, request.form['location'])
        item.sticker_printed = 'sticker_printed' in request.form
        db.session.commit()
        flash('Consumable updated.', 'success')
        return redirect(url_for('consumables.show', id=item.id))
    return render_template('consumable/form.html', obj=item, action=url_for('consumables.edit', id=item.id), **_refs())


@bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    item = get_or_404(Consumable, id)
    db.session.delete(item)
    db.session.commit()
    flash('Consumable deleted.', 'success')
    return redirect(url_for('consumables.index'))
