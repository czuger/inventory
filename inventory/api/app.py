import logging

from flask import Flask
from flask import redirect
from flask import request
from flask import session
from flask import url_for

from inventory.api.routes import (
    board_game, book, consumable, equipment, miniature, rulebook, tablecloth, terrain,
)
from inventory.api.translations import TRANSLATIONS
from inventory.db.association import Association
from inventory.libs.initialization import initialize

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(filename)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

# Suppress Flask/Werkzeug debug logs
logging.getLogger("werkzeug").setLevel(logging.INFO)
logging.getLogger("flask").setLevel(logging.INFO)
logging.getLogger("pymongo").setLevel(logging.INFO)

ADMIN = True

app = Flask(__name__)

app_context = initialize(app)
app = app_context.app

app.secret_key = app_context.secret_key
app.config['ADMIN'] = ADMIN


@app.context_processor
def inject_translations():
    lang = session.get('lang', 'fr')
    return dict(t=TRANSLATIONS[lang], lang=lang, admin=app.config['ADMIN'])


@app.route('/set-language/<lang>')
def set_language(lang):
    if lang in ('en', 'fr'):
        session['lang'] = lang
    return redirect(request.referrer or url_for('index'))


app.register_blueprint(tablecloth.bp)
app.register_blueprint(miniature.bp)
app.register_blueprint(terrain.bp)
app.register_blueprint(rulebook.bp)
app.register_blueprint(board_game.bp)
app.register_blueprint(book.bp)
app.register_blueprint(equipment.bp)
app.register_blueprint(consumable.bp)


@app.route("/")
def index():
    assoc = Association.objects.first()
    if assoc is None:
        return "No association found.", 404
    return redirect(url_for("miniatures.index", slug=assoc.slug))


if __name__ == "__main__":
    app.run(debug=False)
