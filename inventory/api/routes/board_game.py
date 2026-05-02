from flask import Blueprint, flash, g, redirect, render_template, request, url_for

from inventory.api.utils import register_assoc_hooks, register_borrow_routes, register_image_routes, register_sticker_routes
from inventory.db.board_game import BoardGame
from inventory.db.constants import CATEGORIES
from inventory.db.location import Location
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('board_games', __name__, url_prefix='/<slug>/board-games')
register_assoc_hooks(bp)
register_image_routes(bp, BoardGame)
register_borrow_routes(bp, 'board_game', BoardGame)
register_sticker_routes(bp, BoardGame, lambda item: [
    item.name,
    *([item.universe] if item.universe else []),
    f"Qté : {item.quantity}",
    f"{item.location.room}{' – ' + item.location.spot if item.location.spot else ''}",
])


def _refs():
    return dict(
        default_category='Board Game',
        categories=CATEGORIES,
        locations=Location.objects.filter(association=g.assoc),
    )


@bp.route('/')
def index():
    items = BoardGame.objects.filter(association=g.assoc)
    return render_template('board_game/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(BoardGame, id)
    return render_template('board_game/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = BoardGame(
            association=g.assoc,
            category=request.form['category'],
            name=request.form['name'],
            universe=request.form.get('universe', ''),
            quantity=int(request.form.get('quantity') or 1),
            location=Location.objects.get(id=request.form['location']),
        )
        item.save()
        flash('Board game created.', 'success')
        return redirect(url_for('board_games.show', id=item.id))
    return render_template('board_game/form.html', obj=None, action=url_for('board_games.create'), **_refs())


@bp.route('/<id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = get_or_404(BoardGame, id)
    if request.method == 'POST':
        item.association = g.assoc
        item.category = request.form['category']
        item.name = request.form['name']
        item.universe = request.form.get('universe', '')
        item.quantity = int(request.form.get('quantity') or 1)
        item.location = Location.objects.get(id=request.form['location'])
        item.save()
        flash('Board game updated.', 'success')
        return redirect(url_for('board_games.show', id=item.id))
    return render_template('board_game/form.html', obj=item, action=url_for('board_games.edit', id=item.id), **_refs())


@bp.route('/<id>/delete', methods=['POST'])
def delete(id):
    item = get_or_404(BoardGame, id)
    item.delete()
    flash('Board game deleted.', 'success')
    return redirect(url_for('board_games.index'))
