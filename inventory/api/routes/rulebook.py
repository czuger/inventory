from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from inventory.db.category import Category
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.rulebook import Rulebook
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('rulebooks', __name__, url_prefix='/rulebooks')


def _refs():
    return dict(
        categories=Category.objects.order_by('name'),
        games=Game.objects.order_by('name'),
        locations=Location.objects.filter(association=current_app.config['CURRENT_ASSOCIATION']),
    )


@bp.route('/')
def index():
    assoc = current_app.config['CURRENT_ASSOCIATION']
    items = Rulebook.objects.filter(association=assoc)
    return render_template('rulebook/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Rulebook, id)
    return render_template('rulebook/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Rulebook(
            association=current_app.config['CURRENT_ASSOCIATION'],
            category=Category.objects.get(id=request.form['category']),
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
        item.association = current_app.config['CURRENT_ASSOCIATION']
        item.category = Category.objects.get(id=request.form['category'])
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
