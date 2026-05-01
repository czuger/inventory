from flask import Blueprint, flash, redirect, render_template, request, url_for

from inventory.db.association import Association
from inventory.db.board_game import BoardGame
from inventory.db.category import Category
from inventory.db.location import Location
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('board_games', __name__, url_prefix='/board-games')


def _refs():
    return dict(
        associations=Association.objects.order_by('name'),
        categories=Category.objects.order_by('name'),
        locations=Location.objects.all(),
    )


@bp.route('/')
def index():
    items = BoardGame.objects.all()
    return render_template('board_game/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(BoardGame, id)
    return render_template('board_game/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = BoardGame(
            association=Association.objects.get(id=request.form['association']),
            category=Category.objects.get(id=request.form['category']),
            name=request.form['name'],
            universe=request.form.get('universe', ''),
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
        item.association = Association.objects.get(id=request.form['association'])
        item.category = Category.objects.get(id=request.form['category'])
        item.name = request.form['name']
        item.universe = request.form.get('universe', '')
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
