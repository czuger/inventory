from mongoengine import Document, StringField, FloatField, ListField, EmbeddedDocument, EmbeddedDocumentField


class Localisation(EmbeddedDocument):
    """Embedded document for item location."""
    salle = StringField(choices=["grande salle", "petite salle"])
    emplacement = StringField(choices=[
        "placard 1 porte",
        "placard 2 portes",
        "pièce 1",
        "vitrine 1",
        "vitrine 2",
        "pièce 2",
        "armoire 1",
        "armoire 2"
    ])


class Quantite(EmbeddedDocument):
    """Embedded document for quantity with unit."""
    nombre = FloatField()
    unite = StringField()
    details = StringField()  # e.g. "1 (latex) +4 (floquées)", "11 + 8 + 9"


class Dimensions(EmbeddedDocument):
    """Embedded document for item dimensions in inches and cm."""
    largeur_pouces = FloatField()
    longueur_pouces = FloatField()
    largeur_cm = FloatField()
    longueur_cm = FloatField()


class Item(Document):
    """Main inventory document.

    Args:
        code: Hierarchical code (e.g. 1.1.1.1).
        categorie: Top-level category (e.g. 1.1.support de jeu).
        sous_categorie: Sub-category (e.g. 1.1.1.nappe de jeu).
        label: Item label.
        quantite: Item quantity with unit.
        remarques: Additional remarks.
        localisation: Item location.
        tags: List of tags.
        dimensions: Item dimensions in inches and cm.
        echelle: Item scale in mm (e.g. 28mm, 15mm).
    """
    code = StringField()
    categorie = StringField()
    sous_categorie = StringField()
    label = StringField()
    quantite = EmbeddedDocumentField(Quantite)
    remarques = StringField()
    localisation = EmbeddedDocumentField(Localisation)  # single location
    tags = ListField(StringField())
    dimensions = EmbeddedDocumentField(Dimensions)
    echelle = StringField()  # e.g. "28mm", "15mm"

    meta = {"collection": "inventaire"}
