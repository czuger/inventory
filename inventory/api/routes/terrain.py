from flask import Blueprint, flash, redirect, render_template, request, url_for

from inventory.db.association import Association
from inventory.db.category import Category
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.scale import Scale
from inventory.db.terrain import Terrain
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('terrains', __name__, url_prefix='/terrains')


def _refs():
    return dict(
        associations=Association.objects.order_by('name'),
        categories=Category.objects.order_by('name'),
        games=Game.objects.order_by('name'),
        scales=Scale.objects.order_by('value'),
        locations=Location.objects.all(),
    )


@bp.route('/')
def index():
    items = Terrain.objects.all()
    return render_template('terrain/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Terrain, id)
    return render_template('terrain/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Terrain(
            association=Association.objects.get(id=request.form['association']),
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
        item.association = Association.objects.get(id=request.form['association'])
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
