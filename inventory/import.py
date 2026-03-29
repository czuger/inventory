import json

from mongoengine import connect
from pymongo import MongoClient

from inventory.libs.item import Localisation, Quantite, Dimensions, Item


def load_inventory(json_file: str, db_url: str = "mongodb://root:foo@nuc150:27017/grognards?authSource=admin"):
    """Load inventory data from JSON file into MongoDB.

    Args:
        json_file: Path to the JSON file.
        db_url: MongoDB connection URL.
    """
    connect(
        db="grognards",
        host="nuc150",
        port=27017,
        username="root",
        password="foo",
        authentication_source="admin"
    )

    # Connect to MongoDB
    client = MongoClient("mongodb://root:foo@nuc150:27017/?authSource=admin")

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    success = 0
    errors = 0
    skipped = 0

    for item in data:
        # Build localisation if present
        localisation = None
        if item.get("localisation"):
            localisation = Localisation(
                salle=item["localisation"].get("salle"),
                emplacement=item["localisation"].get("emplacement")
            )

        # Build quantite if present
        quantite = None
        if item.get("quantite"):
            quantite = Quantite(
                nombre=item["quantite"].get("nombre"),
                unite=item["quantite"].get("unite"),
                details=item["quantite"].get("details")
            )

        # Build dimensions if present
        dimensions = None
        if item.get("dimensions"):
            dimensions = Dimensions(
                largeur_pouces=item["dimensions"].get("largeur_pouces"),
                longueur_pouces=item["dimensions"].get("longueur_pouces"),
                largeur_cm=item["dimensions"].get("largeur_cm"),
                longueur_cm=item["dimensions"].get("longueur_cm")
            )

        # Create and save inventory item
        inventaire = Item(
            code=item.get("code"),
            categorie=item.get("categorie"),
            sous_categorie=item.get("sous_categorie"),
            label=item.get("label"),
            quantite=quantite,
            remarques=item.get("remarques"),
            localisation=localisation,
            tags=item.get("tags", []),
            dimensions=dimensions,
            echelle=item.get("echelle")
        )

        # Insert only if not exist (check by code)
        if not Item.objects(code=item.get("code")).first():
            inventaire.save()
            success += 1
            print(f"✓ [{item.get('code')}] {item.get('label')} inserted")
        else:
            print(f"⚠ [{item.get('code')}] {item.get('label')} already exists, skipping")
            skipped += 1

    print(f"\n{'=' * 50}")
    print(f"✓ {success} articles inserted")
    print(f"⚠ {skipped} articles skipped (already exist)")
    print(f"✗ {errors} errors")
    print(f"{'=' * 50}")


def clear_inventory():
    """Clear all inventory items from MongoDB."""
    count = Item.objects.count()
    Item.objects.delete()
    print(f"✓ {count} articles supprimés")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Load inventory data into MongoDB")
    parser.add_argument(
        "json_file",
        help="Path to the JSON file"
    )
    parser.add_argument(
        "--db-url",
        default="mongodb://localhost:27017/grognards",
        help="MongoDB connection URL (default: mongodb://localhost:27017/grognards)"
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing inventory before loading"
    )
    args = parser.parse_args()

    if args.clear:
        connect(host=args.db_url)
        print("Suppression des données existantes...")
        clear_inventory()

    load_inventory(args.json_file, args.db_url)
