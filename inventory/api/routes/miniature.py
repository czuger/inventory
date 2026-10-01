from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select

from inventory.api.item_labels import get_sticker_lines
from inventory.api.utils import register_assoc_hooks, register_borrow_routes, register_duplicate_routes, register_image_routes, register_sticker_routes
from inventory.db.base import db
from inventory.db.constants import CATEGORIES, SCALES
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.miniature import Miniature
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('miniatures', __name__, url_prefix='/<slug>/miniatures')
register_assoc_hooks(bp)
register_image_routes(bp, Miniature)
register_borrow_routes(bp, 'miniature', Miniature)
register_duplicate_routes(bp, 'miniature', Miniature)
register_sticker_routes(bp, Miniature, lambda item: get_sticker_lines('miniature', item))


def _refs():
    return dict(
        default_category='Miniature',
        categories=CATEGORIES,
        games=db.session.scalars(select(Game).order_by(Game.name)).all(),
        scales=SCALES,
        locations=db.session.scalars(select(Location).filter_by(association=g.assoc)).all(),
    )


@bp.route('/')
def index():
    items = db.session.scalars(select(Miniature).filter_by(association=g.assoc)).all()
    return render_template('miniature/list.html', items=items)


@bp.route('/<int:id>')
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
            game=get_or_404(Game, request.form['game']),
            scale=request.form['scale'],
            quantity=int(request.form.get('quantity') or 1),
            location=get_or_404(Location, request.form['location']),
        )
        db.session.add(item)
        db.session.commit()
        flash('Miniature created.', 'success')
        return redirect(url_for('miniatures.show', id=item.id))
    return render_template('miniature/form.html', obj=None, action=url_for('miniatures.create'), **_refs())


@bp.route('/<int:id>/edit', methods=['GET', 'POST'])
def edit(id):
    item = get_or_404(Miniature, id)
    if request.method == 'POST':
        item.association = g.assoc
        item.category = request.form['category']
        item.type = request.form['type']
        item.game = get_or_404(Game, request.form['game'])
        item.scale = request.form['scale']
        item.quantity = int(request.form.get('quantity') or 1)
        item.location = get_or_404(Location, request.form['location'])
        item.sticker_printed = 'sticker_printed' in request.form
        db.session.commit()
        flash('Miniature updated.', 'success')
        return redirect(url_for('miniatures.show', id=item.id))
    return render_template('miniature/form.html', obj=item, action=url_for('miniatures.edit', id=item.id), **_refs())


@bp.route('/<int:id>/delete', methods=['POST'])
def delete(id):
    item = get_or_404(Miniature, id)
    db.session.delete(item)
    db.session.commit()
    flash('Miniature deleted.', 'success')
    return redirect(url_for('miniatures.index'))
