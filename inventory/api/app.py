import logging

from flask import Flask
from flask import redirect
from flask import url_for

from inventory.api.routes import (
    board_game, book, consumable, equipment, miniature, rulebook, tablecloth, terrain,
)
from inventory.db.association import Association as AssociationModel
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

app = Flask(__name__)

app_context = initialize(app)
app = app_context.app

app.secret_key = app_context.secret_key

app.register_blueprint(tablecloth.bp)
app.register_blueprint(miniature.bp)
app.register_blueprint(terrain.bp)
app.register_blueprint(rulebook.bp)
app.register_blueprint(board_game.bp)
app.register_blueprint(book.bp)
app.register_blueprint(equipment.bp)
app.register_blueprint(consumable.bp)

CURRENT_ASSOCIATION_NAME = "Les Grognards du Dimanche"
current_assoc = AssociationModel.objects(name=CURRENT_ASSOCIATION_NAME).first()
if current_assoc is None:
    current_assoc = AssociationModel(name=CURRENT_ASSOCIATION_NAME).save()
app.config['CURRENT_ASSOCIATION'] = current_assoc


@app.route("/")
def index():
    return redirect(url_for("miniatures.index"))


if __name__ == "__main__":
    app.run(debug=False)
