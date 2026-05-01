from flask import Blueprint, flash, redirect, render_template, request, url_for

from inventory.db.association import Association
from inventory.db.category import Category
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.miniature import Miniature
from inventory.db.scale import Scale
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('miniatures', __name__, url_prefix='/miniatures')


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
    items = Miniature.objects.all()
    return render_template('miniature/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Miniature, id)
    return render_template('miniature/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Miniature(
            association=Association.objects.get(id=request.form['association']),
            category=Category.objects.get(id=request.form['category']),
            type=request.form['type'],
            game=Game.objects.get(id=request.form['game']),
            scale=Scale.objects.get(id=request.form['scale']),
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
        item.association = Association.objects.get(id=request.form['association'])
        item.category = Category.objects.get(id=request.form['category'])
        item.type = request.form['type']
        item.game = Game.objects.get(id=request.form['game'])
        item.scale = Scale.objects.get(id=request.form['scale'])
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
