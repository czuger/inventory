import logging

from flask import Flask, render_template, request, redirect, url_for, flash

from inventory.libs.categories import Category
from inventory.libs.get_or_404 import get_or_404
from inventory.libs.initialization import initialize
from inventory.libs.item import Item, Quantite, Localisation, Dimensions

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(filename)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

app = Flask(__name__)

app_context = initialize(app)
app = app_context.app

app.secret_key = app_context.secret_key


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
def show(id):
    item = get_or_404(Item, id)
    return render_template("show.html", item=item)


@app.route("/item/<id>/edit", methods=["GET", "POST"])
def edit(id):
    item = get_or_404(Item, id)

    if request.method == "POST":
        item.code = request.form.get("code")
        item.categorie = request.form.get("categorie")
        item.sous_categorie = request.form.get("sous_categorie")
        item.label = request.form.get("label")
        item.remarques = request.form.get("remarques")
        item.echelle = request.form.get("echelle")
        item.tags = [t.strip() for t in request.form.get("tags", "").split(",") if t.strip()]

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
