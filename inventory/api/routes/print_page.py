import io

from flask import Blueprint, abort, g, render_template, request, send_file, url_for

from inventory.api.item_labels import get_list_row, get_sticker_lines
from inventory.api.pdf import make_list_pdf, make_stickers_pdf
from inventory.api.utils import register_assoc_hooks
from inventory.db.board_game import BoardGame
from inventory.db.book import Book
from inventory.db.constants import CATEGORIES
from inventory.db.consumable import Consumable
from inventory.db.equipment import Equipment
from inventory.db.miniature import Miniature
from inventory.db.rulebook import Rulebook
from inventory.db.tablecloth import Tablecloth
from inventory.db.terrain import Terrain

bp = Blueprint('print_page', __name__, url_prefix='/<slug>/print')
register_assoc_hooks(bp)


@bp.before_request
def require_admin():
    if not (getattr(g, 'current_user', None) and g.current_user.is_admin):
        abort(403)


ITEM_TYPES = [
    ('miniature',  'Miniature',  Miniature,  'miniatures'),
    ('terrain',    'Terrain',    Terrain,    'terrains'),
    ('tablecloth', 'Tablecloth', Tablecloth, 'tablecloths'),
    ('rulebook',   'Rulebook',   Rulebook,   'rulebooks'),
    ('board_game', 'Board Game', BoardGame,  'board_games'),
    ('book',       'Book',       Book,       'books'),
    ('equipment',  'Equipment',  Equipment,  'equipment'),
    ('consumable', 'Consumable', Consumable, 'consumables'),
]


@bp.route('/')
def index():
    selected = request.args.get('category', '')
    return render_template('print/index.html', categories=CATEGORIES, selected=selected)


@bp.route('/stickers', methods=['POST'])
def stickers():
    category = request.form.get('category', '')
    data = []
    for item_type, cat_name, Model, bp_name in ITEM_TYPES:
        if category and cat_name != category:
            continue
        for item in Model.objects.filter(association=g.assoc):
            item_url = url_for(bp_name + '.show', id=item.id, _external=True)
            data.append((get_sticker_lines(item_type, item), item_url))
    pdf_bytes = make_stickers_pdf(data)
    return send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf',
                     as_attachment=False, download_name='stickers.pdf')


@bp.route('/list', methods=['POST'])
def print_list():
    category = request.form.get('category', '')
    rows = []
    for item_type, cat_name, Model, _ in ITEM_TYPES:
        if category and cat_name != category:
            continue
        for item in Model.objects.filter(association=g.assoc):
            rows.append(get_list_row(item_type, item))
    title = category if category else 'Inventaire'
    pdf_bytes = make_list_pdf(title, rows)
    return send_file(io.BytesIO(pdf_bytes), mimetype='application/pdf',
                     as_attachment=False, download_name='list.pdf')
