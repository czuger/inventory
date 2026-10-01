from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select

from inventory.api.item_labels import get_sticker_lines
from inventory.api.utils import register_assoc_hooks, register_borrow_routes, register_duplicate_routes, register_image_routes, register_sticker_routes
from inventory.db.base import db
from inventory.db.constants import CATEGORIES, SCALES
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.terrain import Terrain
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('terrains', __name__, url_prefix='/<slug>/terrains')
register_assoc_hooks(bp)
register_image_routes(bp, Terrain)
register_borrow_routes(bp, 'terrain', Terrain)
register_duplicate_routes(bp, 'terrain', Terrain)
register_sticker_routes(bp, Terrain, lambda item: get_sticker_lines('terrain', item))


def _refs():
    return dict(
        default_category='Terrain',
        categories=CATEGORIES,
        games=db.session.scalars(select(Game).order_by(Game.name)).all(),
        scales=SCALES,
        locations=db.session.scalars(select(Location).filter_by(association=g.assoc)).all(),
    )


@bp.route('/')
def index():
    items = db.session.scalars(select(Terrain).filter_by(association=g.assoc)).all()
    return render_template('terrain/list.html', items=items)


@bp.route('/<int:id>')
def show(id):
    item = get_or_404(Terrain, id)
    return render_template('terrain/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Terrain(
            association=g.assoc,
            category=request.form['category'],
            type=request.form['type'],
            game=get_or_404(Game, request.form['game']),
            scale=request.form['scale'],
            theater=request.form.get('theater', ''),
            quantity=int(request.form.get('quantity') or 1),
            location=get_or_404(Location, request.form['location']),
        )
        db.session.add(item)
        db.session.commit()
        flash('Terrain created.', 'success')
        return redirect(url_for('terrains.show', id=item.id))
    return render_template('terrain/form.html', obj=None, action=url_for('terrains.create'), **_refs())


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = get_or_404(Terrain, id)
    if request.method == 'POST':
        item.association = g.assoc
        item.category = request.form['category']
        item.type = request.form['type']
        item.game = get_or_404(Game, request.form['game'])
        item.scale = request.form['scale']
        item.theater = request.form.get('theater', '')
        item.quantity = int(request.form.get('quantity') or 1)
        item.location = get_or_404(Location, request.form['location'])
        item.sticker_printed = 'sticker_printed' in request.form
        db.session.commit()
        flash('Terrain updated.', 'success')
        return redirect(url_for('terrains.show', id=item.id))
    return render_template('terrain/form.html', obj=item, action=url_for('terrains.edit', id=item.id), **_refs())


@bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    item = get_or_404(Terrain, id)
    db.session.delete(item)
    db.session.commit()
    flash('Terrain deleted.', 'success')
    return redirect(url_for('terrains.index'))
