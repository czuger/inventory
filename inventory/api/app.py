import base64
import logging

from bson import Binary
from flask import Flask
from flask import flash
from flask import redirect
from flask import render_template
from flask import request
from flask import url_for

from inventory.api.routes import (
    board_game, book, consumable, equipment, miniature, rulebook, tablecloth, terrain,
)
from inventory.db.association import Association as AssociationModel
from inventory.libs.categories import Category
from inventory.libs.get_or_404 import get_or_404
from inventory.libs.initialization import initialize
from inventory.libs.item import Dimensions
from inventory.libs.item import Item
from inventory.libs.item import Localisation
from inventory.libs.item import Quantite

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
    categories = Category.objects.order_by("category")
    categories_dict = {cat.category: cat.sub_categories for cat in categories}

    cat = request.args.get("cat")
    sous = request.args.get("sous")

    items = Item.objects.order_by("categorie", "sous_category", "label")

    if cat:
        items = items.filter(categorie=cat)

    if sous and sous in categories_dict[cat]:
        items = items.filter(sous_categorie=sous)

    return render_template("index.html", items=items, categories=categories, cat=cat, sous=sous)


@app.route("/item/<id>")
def show(id: str):
    """Show a single item.

    Args:
        id: The item id.
    """
    item = get_or_404(Item, id)
    images_b64 = [base64.b64encode(m).decode('utf-8') for m in item.medias]
    return render_template("show.html", item=item, images_b64=images_b64)


@app.route("/item/<id>/edit", methods=["GET", "POST"])
def edit(id):
    item = get_or_404(Item, id)
    item: Item

    if request.method == "POST":
        item.code = request.form.get("code")
        item.categorie = request.form.get("categorie")
        item.sous_categorie = request.form.get("sous_categorie")
        item.label = request.form.get("label")
        item.remarques = request.form.get("remarques")
        item.echelle = request.form.get("echelle")
        item.tags = [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()]

        media_data = None
        media_file = request.files.get('media')
        if media_file and media_file.filename:
            media_data = Binary(media_file.read())
        item.medias.append(media_data)

        item.quantite = Quantite(
            nombre=request.form.get("quantite_nombre") or None,
            unite=request.form.get("quantite_unite"),
            details=request.form.get("quantite_details")
        )

        item.localisation = Localisation(
            salle=request.form.get("salle") or None,
            emplacement=request.form.get("emplacement") or None
        )

        item.dimensions = Dimensions(
            largeur_pouces=request.form.get("largeur_pouces") or None,
            longueur_pouces=request.form.get("longueur_pouces") or None,
            largeur_cm=request.form.get("largeur_cm") or None,
            longueur_cm=request.form.get("longueur_cm") or None
        )

        item.save()
        flash("Modifications enregistrées.", "success")
        return redirect(url_for("show", id=item.id))

    return render_template("edit.html", item=item)


if __name__ == "__main__":
    app.run(debug=False)
