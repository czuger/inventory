from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from inventory.api.utils import register_assoc_hooks, register_image_routes
from inventory.db.constants import CATEGORIES, TABLECLOTH_SIZES, TABLECLOTH_SIZES_INCHES
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.tablecloth import Tablecloth, TABLECLOTH_MATERIALS
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('tablecloths', __name__, url_prefix='/<slug>/tablecloths')
register_assoc_hooks(bp)
register_image_routes(bp, Tablecloth)


def _refs():
    return dict(
        default_category='Tablecloth',
        categories=CATEGORIES,
        games=Game.objects.order_by('name'),
        sizes=TABLECLOTH_SIZES,
        sizes_inches=TABLECLOTH_SIZES_INCHES,
        locations=Location.objects.filter(association=g.assoc),
        materials=TABLECLOTH_MATERIALS,
    )


@bp.route('/')
def index():
    items = Tablecloth.objects.filter(association=g.assoc)
    return render_template('tablecloth/list.html', items=items, sizes_inches=TABLECLOTH_SIZES_INCHES)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Tablecloth, id)
    return render_template('tablecloth/show.html', item=item, sizes_inches=TABLECLOTH_SIZES_INCHES)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Tablecloth(
            association=g.assoc,
            category=request.form['category'],
            quantity=int(request.form.get('quantity') or 1),
            type=request.form['type'],
            material=request.form.get('material') or None,
            game=Game.objects.get(id=request.form['game']),
            size=request.form['size'],
            remarks=request.form.get('remarks') or None,
            location=Location.objects.get(id=request.form['location']),
        )
        item.save()
        flash('Tablecloth created.', 'success')
        return redirect(url_for('tablecloths.show', id=item.id))
    return render_template('tablecloth/form.html', obj=None, action=url_for('tablecloths.create'), **_refs())


@bp.route('/<id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = get_or_404(Tablecloth, id)
    if request.method == 'POST':
        item.association = g.assoc
        item.category = request.form['category']
        item.quantity = int(request.form.get('quantity') or 1)
        item.type = request.form['type']
        item.material = request.form.get('material') or None
        item.game = Game.objects.get(id=request.form['game'])
        item.size = request.form['size']
        item.remarks = request.form.get('remarks') or None
        item.location = Location.objects.get(id=request.form['location'])
        item.save()
        flash('Tablecloth updated.', 'success')
        return redirect(url_for('tablecloths.show', id=item.id))
    return render_template('tablecloth/form.html', obj=item, action=url_for('tablecloths.edit', id=item.id), **_refs())


@bp.route('/<id>/delete', methods=['POST'])
def delete(id):
    item = get_or_404(Tablecloth, id)
    item.delete()
    flash('Tablecloth deleted.', 'success')
    return redirect(url_for('tablecloths.index'))
