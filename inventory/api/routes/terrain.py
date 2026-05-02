from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from inventory.api.item_labels import get_sticker_lines
from inventory.api.utils import register_assoc_hooks, register_borrow_routes, register_image_routes, register_sticker_routes
from inventory.db.constants import CATEGORIES, SCALES
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.terrain import Terrain
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('terrains', __name__, url_prefix='/<slug>/terrains')
register_assoc_hooks(bp)
register_image_routes(bp, Terrain)
register_borrow_routes(bp, 'terrain', Terrain)
register_sticker_routes(bp, Terrain, lambda item: get_sticker_lines('terrain', item))


def _refs():
    return dict(
        default_category='Terrain',
        categories=CATEGORIES,
        games=Game.objects.order_by('name'),
        scales=SCALES,
        locations=Location.objects.filter(association=g.assoc),
    )


@bp.route('/')
def index():
    items = Terrain.objects.filter(association=g.assoc)
    return render_template('terrain/list.html', items=items)


@bp.route('/<id>')
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
            game=Game.objects.get(id=request.form['game']),
            scale=request.form['scale'],
            theater=request.form.get('theater', ''),
            quantity=int(request.form.get('quantity') or 1),
            location=Location.objects.get(id=request.form['location']),
        )
        item.save()
        flash('Terrain created.', 'success')
        return redirect(url_for('terrains.show', id=item.id))
    return render_template('terrain/form.html', obj=None, action=url_for('terrains.create'), **_refs())


@bp.route('/<id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = get_or_404(Terrain, id)
    if request.method == 'POST':
        item.association = g.assoc
        item.category = request.form['category']
        item.type = request.form['type']
        item.game = Game.objects.get(id=request.form['game'])
        item.scale = request.form['scale']
        item.theater = request.form.get('theater', '')
        item.quantity = int(request.form.get('quantity') or 1)
        item.location = Location.objects.get(id=request.form['location'])
        item.sticker_printed = 'sticker_printed' in request.form
        item.save()
        flash('Terrain updated.', 'success')
        return redirect(url_for('terrains.show', id=item.id))
    return render_template('terrain/form.html', obj=item, action=url_for('terrains.edit', id=item.id), **_refs())


@bp.route('/<id>/delete', methods=['POST'])
def delete(id):
    item = get_or_404(Terrain, id)
    item.delete()
    flash('Terrain deleted.', 'success')
    return redirect(url_for('terrains.index'))
