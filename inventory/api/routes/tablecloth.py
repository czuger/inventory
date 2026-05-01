from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from inventory.db.category import Category
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.tablecloth import Tablecloth
from inventory.db.tablecloth_size import TableclothSize
from inventory.libs.get_or_404 import get_or_404

bp = Blueprint('tablecloths', __name__, url_prefix='/tablecloths')


def _refs():
    return dict(
        categories=Category.objects.order_by('name'),
        games=Game.objects.order_by('name'),
        sizes=TableclothSize.objects.all(),
        locations=Location.objects.filter(association=current_app.config['CURRENT_ASSOCIATION']),
    )


@bp.route('/')
def index():
    assoc = current_app.config['CURRENT_ASSOCIATION']
    items = Tablecloth.objects.filter(association=assoc)
    return render_template('tablecloth/list.html', items=items)


@bp.route('/<id>')
def show(id):
    item = get_or_404(Tablecloth, id)
    return render_template('tablecloth/show.html', item=item)


@bp.route('/new', methods=['GET', 'POST'])
def create():
    if request.method == 'POST':
        item = Tablecloth(
            association=current_app.config['CURRENT_ASSOCIATION'],
            category=Category.objects.get(id=request.form['category']),
            type=request.form['type'],
            game=Game.objects.get(id=request.form['game']),
            size=TableclothSize.objects.get(id=request.form['size']),
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
        item.association = current_app.config['CURRENT_ASSOCIATION']
        item.category = Category.objects.get(id=request.form['category'])
        item.type = request.form['type']
        item.game = Game.objects.get(id=request.form['game'])
        item.size = TableclothSize.objects.get(id=request.form['size'])
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
