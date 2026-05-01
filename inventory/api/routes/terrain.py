from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from inventory.db.category import Category
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.scale import Scale
from inventory.db.terrain import Terrain
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('terrains', __name__, url_prefix='/terrains')


def _refs():
    return dict(
        categories=Category.objects.order_by('name'),
        games=Game.objects.order_by('name'),
        scales=Scale.objects.order_by('value'),
        locations=Location.objects.filter(association=current_app.config['CURRENT_ASSOCIATION']),
    )


@bp.route('/')
def index():
    assoc = current_app.config['CURRENT_ASSOCIATION']
    items = Terrain.objects.filter(association=assoc)
    return render_template('terrain/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Terrain, id)
    return render_template('terrain/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Terrain(
            association=current_app.config['CURRENT_ASSOCIATION'],
            category=Category.objects.get(id=request.form['category']),
            type=request.form['type'],
            game=Game.objects.get(id=request.form['game']),
            scale=Scale.objects.get(id=request.form['scale']),
            theater=request.form.get('theater', ''),
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
        item.association = current_app.config['CURRENT_ASSOCIATION']
        item.category = Category.objects.get(id=request.form['category'])
        item.type = request.form['type']
        item.game = Game.objects.get(id=request.form['game'])
        item.scale = Scale.objects.get(id=request.form['scale'])
        item.theater = request.form.get('theater', '')
        item.location = Location.objects.get(id=request.form['location'])
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
