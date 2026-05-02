from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from inventory.api.utils import register_assoc_hooks, register_image_routes
from inventory.db.constants import CATEGORIES, SCALES
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.miniature import Miniature
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('miniatures', __name__, url_prefix='/<slug>/miniatures')
register_assoc_hooks(bp)
register_image_routes(bp, Miniature)


def _refs():
    return dict(
        categories=CATEGORIES,
        games=Game.objects.order_by('name'),
        scales=SCALES,
        locations=Location.objects.filter(association=g.assoc),
    )


@bp.route('/')
def index():
    items = Miniature.objects.filter(association=g.assoc)
    return render_template('miniature/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Miniature, id)
    return render_template('miniature/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Miniature(
            association=g.assoc,
            category=request.form['category'],
            type=request.form['type'],
            game=Game.objects.get(id=request.form['game']),
            scale=request.form['scale'],
            quantity=int(request.form.get('quantity') or 1),
            location=Location.objects.get(id=request.form['location']),
        )
        item.save()
        flash('Miniature created.', 'success')
        return redirect(url_for('miniatures.show', id=item.id))
    return render_template('miniature/form.html', obj=None, action=url_for('miniatures.create'), **_refs())


@bp.route('/<id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = get_or_404(Miniature, id)
    if request.method == 'POST':
        item.association = g.assoc
        item.category = request.form['category']
        item.type = request.form['type']
        item.game = Game.objects.get(id=request.form['game'])
        item.scale = request.form['scale']
        item.quantity = int(request.form.get('quantity') or 1)
        item.location = Location.objects.get(id=request.form['location'])
        item.save()
        flash('Miniature updated.', 'success')
        return redirect(url_for('miniatures.show', id=item.id))
    return render_template('miniature/form.html', obj=item, action=url_for('miniatures.edit', id=item.id), **_refs())


@bp.route('/<id>/delete', methods=['POST'])
def delete(id):
    item = get_or_404(Miniature, id)
    item.delete()
    flash('Miniature deleted.', 'success')
    return redirect(url_for('miniatures.index'))
