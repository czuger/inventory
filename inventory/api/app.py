import logging
import os

from flask import Flask, g, redirect, request, session, url_for

from inventory.api.oauth import oauth
from inventory.api.item_labels import get_item_display
from inventory.api.routes import (
    auth, board_game, book, consumable, equipment, miniature, print_page, rulebook, tablecloth, terrain,
)
from inventory.api.translations import TRANSLATIONS
from inventory.db.association import Association
from inventory.db.borrowing import Borrowing
from inventory.db.duplicate_link import DuplicateLink
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


def mounted_under(wsgi_app, prefix):
    """Tell the app it is served under `prefix` (e.g. `/inventory`), in production.

    The proxy strips the prefix before forwarding, so routing already matches —
    but `url_for()`, redirects and static URLs would come out at the site root,
    outside the proxied location. SCRIPT_NAME is the WSGI way to say "this is the
    part of the URL that got you here", and Flask prepends it when building URLs.

    That matters more here than in most apps: every item blueprint is mounted at
    `/<slug>/...` and `register_assoc_hooks` re-injects the slug through
    `url_defaults`, so essentially every link on every page is generated rather
    than written out. Get SCRIPT_NAME wrong and the whole site links to itself
    outside the prefix.

    It is also what makes the Discord callback work: `url_for('auth.callback',
    _external=True)` has to produce the exact redirect URI registered on the
    Discord application, prefix included.

    PATH_INFO is deliberately left untouched: the proxy already stripped it, and
    stripping again would corrupt paths that happen to start with the same word.
    (That is also why gunicorn's SCRIPT_NAME env var is not usable here — it does
    strip PATH_INFO.)
    """
    prefix = "/" + prefix.strip("/")

    def wrapper(environ, start_response):
        environ["SCRIPT_NAME"] = prefix
        return wsgi_app(environ, start_response)

    return wrapper


def create_app(test: bool = False) -> Flask:
    _app = Flask(__name__)

    app_context = initialize(_app, test=test)
    _app = app_context.app
    _app.secret_key = app_context.secret_key
    config = app_context.config

    # Where the proxy serves us from, handed over by deploy/remote.sh from the
    # same deploy/config.sh that rendered the nginx snippet. Unset in dev and
    # ignored under `test`, so both stay at the root.
    url_prefix = "" if test else os.environ.get("URL_PREFIX", "").strip().strip("/")
    if url_prefix:
        _app.wsgi_app = mounted_under(_app.wsgi_app, url_prefix)

    oauth.init_app(_app)
    oauth.register(
        name='discord',
        client_id=config['discord']['client_id'],
        client_secret=config['discord']['client_secret'],
        access_token_url='https://discord.com/api/oauth2/token',
        authorize_url='https://discord.com/api/oauth2/authorize',
        api_base_url='https://discord.com/api/',
        client_kwargs={'scope': 'identify'},
    )

    @_app.before_request
    def load_current_user():
        user_id = session.get('user_id')
        g.current_user = User.objects(id=user_id).first() if user_id else None

    @_app.context_processor
    def inject_globals():
        lang = session.get('lang', 'fr')
        current_user = getattr(g, 'current_user', None)
        return dict(
            t=TRANSLATIONS[lang],
            lang=lang,
            admin=bool(current_user and current_user.is_admin),
            current_user=current_user,
        )

    @_app.template_global()
    def get_borrow_status(item_id, item_type):
        return Borrowing.objects(item_id=str(item_id), item_type=item_type).order_by('-date').first()

    @_app.template_global()
    def get_borrow_history(item_id, item_type):
        return list(Borrowing.objects(item_id=str(item_id), item_type=item_type).order_by('-date'))

    @_app.template_global()
    def get_duplicate_links(item_id, item_type):
        assoc = getattr(g, 'assoc', None)
        links = DuplicateLink.objects(association=assoc).filter(
            __raw__={'$or': [
                {'item1_id': str(item_id), 'item1_type': item_type},
                {'item2_id': str(item_id), 'item2_type': item_type},
            ]}
        )
        result = []
        for link in links:
            if link.item1_id == str(item_id) and link.item1_type == item_type:
                other_id, other_type = link.item2_id, link.item2_type
            else:
                other_id, other_type = link.item1_id, link.item1_type
            label, endpoint = get_item_display(other_type, other_id)
            if label is None:
                continue
            result.append({
                'link_id':  str(link.id),
                'label':    label,
                'endpoint': endpoint,
                'other_id': other_id,
            })
        return result

    @_app.route('/set-language/<lang>')
    def set_language(lang):
        if lang in ('en', 'fr'):
            session['lang'] = lang
        return redirect(request.referrer or url_for('index'))

    _app.register_blueprint(auth.bp)
    _app.register_blueprint(tablecloth.bp)
    _app.register_blueprint(miniature.bp)
    _app.register_blueprint(terrain.bp)
    _app.register_blueprint(rulebook.bp)
    _app.register_blueprint(board_game.bp)
    _app.register_blueprint(book.bp)
    _app.register_blueprint(equipment.bp)
    _app.register_blueprint(consumable.bp)
    _app.register_blueprint(print_page.bp)

    @_app.route("/health")
    def health():
        """What the deploy gates on: `docker exec` probes this from inside the
        container after every start (deploy/remote.sh), and the image's
        HEALTHCHECK hits the same path.

        Deliberately does NOT touch MongoDB. It answers the only question the
        deploy can act on — did gunicorn come up with this image — and a probe
        that also failed when the database blinked would roll back a perfectly
        good release. It is registered at the root, so URL_PREFIX (which only
        changes generated URLs) leaves its path alone.
        """
        return "ok", 200, {"Content-Type": "text/plain"}

    @_app.route("/")
    def index():
        assoc = Association.objects.first()
        if assoc is None:
            return "No association found.", 404
        return redirect(url_for("miniatures.index", slug=assoc.slug))

    return _app


app = create_app()

if __name__ == "__main__":
    app.run(debug=False)
