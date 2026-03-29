import json

from old_version.inventory.db.items import Typology, Category, Subcategory, Location, Item, create_session, init_db


def import_inventory_data(db_session, data_file):
    # Lire le fichier JSON
    with open(data_file, 'r', encoding='utf-8') as f:
        items_data = json.load(f)

    # Traiter chaque élément
    for item_data in items_data:
        # 1. Gérer la typologie
        typology_name = item_data.get('typology')
        typology = None
        if typology_name:
            typology = db_session.query(Typology).filter_by(name=typology_name).first()
            if not typology:
                typology = Typology(name=typology_name)
                db_session.add(typology)
                db_session.flush()  # Pour obtenir l'ID

        # 2. Gérer la catégorie
        category_name = item_data.get('category')
        category = None
        if category_name and typology:
            category = (db_session.query(Category)
                        .filter_by(name=category_name, typology_id=typology.id)
                        .first())
            if not category:
                category = Category(name=category_name, typology=typology)
                db_session.add(category)
                db_session.flush()

        # 3. Gérer la sous-catégorie
        subcategory_name = item_data.get('subcategory')
        subcategory = None
        if subcategory_name and category:
            subcategory = (db_session.query(Subcategory)
                           .filter_by(name=subcategory_name, category_id=category.id)
                           .first())
            if not subcategory:
                subcategory = Subcategory(name=subcategory_name, category=category)
                db_session.add(subcategory)
                db_session.flush()

        # 4. Gérer l'emplacement
        location_name = item_data.get('location')
        location = None
        if location_name:
            location = db_session.query(Location).filter_by(name=location_name).first()
            if not location:
                location = Location(name=location_name)
                db_session.add(location)
                db_session.flush()

        # 5. Créer l'item
        name = item_data.get('name')
        if name:
            # Convertir quantity en string si nécessaire
            quantity = item_data.get('quantity')
            if quantity is not None:
                quantity = str(quantity)

            item = Item(
                name=name,
                quantity=quantity,
                remarks=item_data.get('remarks'),
                typology=typology,
                category=category,
                subcategory=subcategory,
                location=location
            )
            db_session.add(item)

    # Enregistrer tous les changements
    db_session.commit()


def main():
    engine = init_db("../config/config.json")
    session = create_session(engine)

    import_inventory_data(session, "../config/input.json")


if __name__ == "__main__":
    main()
