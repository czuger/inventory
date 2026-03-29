from mongoengine import connect

from inventory.libs.categories import Category
from inventory.libs.item import Item

connect(
    db="grognards",
    host="nuc150",
    port=27017,
    username="root",
    password="foo",
    authentication_source="admin"
)

# Build a dict of category -> set of sous_categories
cat_map = {}

for item in Item.objects:
    cat = item.categorie
    sous = item.sous_categorie

    if not cat:
        continue

    if cat not in cat_map:
        cat_map[cat] = set()

    if sous:
        cat_map[cat].add(sous)

# Upsert into Category collection
for cat, sous_set in cat_map.items():
    Category.objects(category=cat).update_one(
        set__category=cat,
        set__sub_categories=sorted(list(sous_set)),
        upsert=True
    )
    print(f"✔ {cat}: {sorted(sous_set)}")

print("Done.")
