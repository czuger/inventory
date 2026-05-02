import logging

from flask import Flask, g, redirect, request, session, url_for

from inventory.api.oauth import oauth
from inventory.api.routes import (
    auth, board_game, book, consumable, equipment, miniature, print_page, rulebook, tablecloth, terrain,
)
from inventory.api.translations import TRANSLATIONS
from inventory.db.association import Association
from inventory.db.borrowing import Borrowing
from inventory.db.user import User
from inventory.libs.initialization import initialize

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(filename)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

logging.getLogger("werkzeug").setLevel(logging.INFO)
logging.getLogger("flask").setLevel(logging.INFO)
logging.getLogger("pymongo").setLevel(logging.INFO)

app = Flask(__name__)

app_context = initialize(app)
app = app_context.app
config = app_context.config

app.secret_key = app_context.secret_key

oauth.init_app(app)
oauth.register(
    name='discord',
    client_id=config['discord']['client_id'],
    client_secret=config['discord']['client_secret'],
    access_token_url='https://discord.com/api/oauth2/token',
    authorize_url='https://discord.com/api/oauth2/authorize',
    api_base_url='https://discord.com/api/',
    client_kwargs={'scope': 'identify'},
)


@app.before_request
def load_current_user():
    user_id = session.get('user_id')
    g.current_user = User.objects(id=user_id).first() if user_id else None


@app.context_processor
def inject_globals():
    lang = session.get('lang', 'fr')
    current_user = getattr(g, 'current_user', None)
    return dict(
        t=TRANSLATIONS[lang],
        lang=lang,
        admin=bool(current_user and current_user.is_admin),
        current_user=current_user,
    )


@app.template_global()
def get_borrow_status(item_id, item_type):
    return Borrowing.objects(item_id=str(item_id), item_type=item_type).order_by('-date').first()


@app.template_global()
def get_borrow_history(item_id, item_type):
    return list(Borrowing.objects(item_id=str(item_id), item_type=item_type).order_by('-date'))


@app.route('/set-language/<lang>')
def set_language(lang):
    if lang in ('en', 'fr'):
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))


app.register_blueprint(auth.bp)
app.register_blueprint(tablecloth.bp)
app.register_blueprint(miniature.bp)
app.register_blueprint(terrain.bp)
app.register_blueprint(rulebook.bp)
app.register_blueprint(board_game.bp)
app.register_blueprint(book.bp)
app.register_blueprint(equipment.bp)
app.register_blueprint(consumable.bp)
app.register_blueprint(print_page.bp)


@app.route("/")
def index():
    assoc = Association.objects.first()
    if assoc is None:
        return "No association found.", 404
    return redirect(url_for("miniatures.index", slug=assoc.slug))


if __name__ == "__main__":
    app.run(debug=False)
