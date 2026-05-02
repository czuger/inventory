from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from inventory.api.utils import register_assoc_hooks, register_borrow_routes, register_image_routes
from inventory.db.constants import CATEGORIES
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.rulebook import Rulebook
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('rulebooks', __name__, url_prefix='/<slug>/rulebooks')
register_assoc_hooks(bp)
register_image_routes(bp, Rulebook)
register_borrow_routes(bp, 'rulebook', Rulebook)


def _refs():
    return dict(
        default_category='Rulebook',
        categories=CATEGORIES,
        games=Game.objects.order_by('name'),
        locations=Location.objects.filter(association=g.assoc),
    )


@bp.route('/')
def index():
    items = Rulebook.objects.filter(association=g.assoc)
    return render_template('rulebook/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Rulebook, id)
    return render_template('rulebook/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Rulebook(
            association=g.assoc,
            category=request.form['category'],
            name=request.form['name'],
            game=Game.objects.get(id=request.form['game']),
            supplement='supplement' in request.form,
            quantity=int(request.form.get('quantity') or 1),
            location=Location.objects.get(id=request.form['location']),
        )
        item.save()
        flash('Rulebook created.', 'success')
        return redirect(url_for('rulebooks.show', id=item.id))
    return render_template('rulebook/form.html', obj=None, action=url_for('rulebooks.create'), **_refs())


@bp.route('/<id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = get_or_404(Rulebook, id)
    if request.method == 'POST':
        item.association = g.assoc
        item.category = request.form['category']
        item.name = request.form['name']
        item.game = Game.objects.get(id=request.form['game'])
        item.supplement = 'supplement' in request.form
        item.quantity = int(request.form.get('quantity') or 1)
        item.location = Location.objects.get(id=request.form['location'])
        item.save()
        flash('Rulebook updated.', 'success')
        return redirect(url_for('rulebooks.show', id=item.id))
    return render_template('rulebook/form.html', obj=item, action=url_for('rulebooks.edit', id=item.id), **_refs())


@bp.route('/<id>/delete', methods=['POST'])
def delete(id):
    item = get_or_404(Rulebook, id)
    item.delete()
    flash('Rulebook deleted.', 'success')
    return redirect(url_for('rulebooks.index'))
