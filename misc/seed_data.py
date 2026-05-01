from mongoengine import *

from inventory.db.association import Association
from inventory.db.board_game import BoardGame
from inventory.db.book import Book
from inventory.db.category import Category
from inventory.db.consumable import Consumable
from inventory.db.equipment import Equipment
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.miniature import Miniature
from inventory.db.rulebook import Rulebook
from inventory.db.scale import Scale
from inventory.db.tablecloth import Tablecloth
from inventory.db.tablecloth_size import TableclothSize
from inventory.db.terrain import Terrain
from inventory.libs.initialization import load_config

config = load_config()

db_name = config['mongo']['database']

connect(
    db=db_name,
    host=config['mongo']['server'],
    port=27017,
    username=config['mongo']['user'],
    password=config['mongo']['pass'],
    authentication_source='admin',
    uuidRepresentation="standard"
)


def get_or_create(model, **kwargs):
    obj = model.objects(**kwargs).first()
    if not obj:
        obj = model(**kwargs).save()
    return obj


def seed():
    # ─────────────────────────────────────────
    # Association
    # ─────────────────────────────────────────
    assoc = get_or_create(Association, name="Les Grognards du Dimanche")

    # ─────────────────────────────────────────
    # Categories
    # ─────────────────────────────────────────
    cat_tablecloth = get_or_create(Category, name="Tablecloth")
    cat_miniature = get_or_create(Category, name="Miniature")
    cat_terrain = get_or_create(Category, name="Terrain")
    cat_rulebook = get_or_create(Category, name="Rulebook")
    cat_boardgame = get_or_create(Category, name="Board Game")
    cat_book = get_or_create(Category, name="Book")
    cat_equipment = get_or_create(Category, name="Equipment")
    cat_consumable = get_or_create(Category, name="Consumable")

    # ─────────────────────────────────────────
    # Games
    # ─────────────────────────────────────────
    game_bolt_action = get_or_create(Game, name="Bolt Action")
    game_flames = get_or_create(Game, name="Flames of War")
    game_black_powder = get_or_create(Game, name="Black Powder")
    game_saga = get_or_create(Game, name="SAGA")
    game_chain_of_cmd = get_or_create(Game, name="Chain of Command")
    game_generic = get_or_create(Game, name="Generic")

    # ─────────────────────────────────────────
    # Scales
    # ─────────────────────────────────────────
    scale_28mm = get_or_create(Scale, value="28mm")
    scale_15mm = get_or_create(Scale, value="15mm")
    scale_10mm = get_or_create(Scale, value="10mm")
    scale_6mm = get_or_create(Scale, value="6mm")

    # ─────────────────────────────────────────
    # Tablecloth Sizes
    # ─────────────────────────────────────────
    size_180x120 = get_or_create(TableclothSize, size_cm="180x120", size_inches='72"x48"')
    size_120x80 = get_or_create(TableclothSize, size_cm="120x80", size_inches='48"x32"')

    # ─────────────────────────────────────────
    # Locations
    # ─────────────────────────────────────────
    loc_upstairs_cab1 = get_or_create(Location, association=assoc, room="Upstairs", spot="Cabinet 1")
    loc_upstairs_cab2 = get_or_create(Location, association=assoc, room="Upstairs", spot="Cabinet 2")
    loc_upstairs_cab3 = get_or_create(Location, association=assoc, room="Upstairs", spot="Cabinet 3")
    loc_downstairs_cab1 = get_or_create(Location, association=assoc, room="Downstairs", spot="Cabinet 1")
    loc_downstairs_cab2 = get_or_create(Location, association=assoc, room="Downstairs", spot="Cabinet 2")
    loc_downstairs_cab3 = get_or_create(Location, association=assoc, room="Downstairs", spot="Cabinet 3")

    # ─────────────────────────────────────────
    # Tablecloths
    # ─────────────────────────────────────────
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Green Meadow", game=game_bolt_action,
        size=size_180x120, location=loc_upstairs_cab1
    ).save()

    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Desert Sand", game=game_flames,
        size=size_120x80, location=loc_upstairs_cab1
    ).save()

    # ─────────────────────────────────────────
    # Miniatures
    # ─────────────────────────────────────────
    Miniature(
        association=assoc, category=cat_miniature,
        type="German Infantry", game=game_bolt_action,
        scale=scale_28mm, quantity=35,
        location=loc_upstairs_cab2
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="British Infantry", game=game_bolt_action,
        scale=scale_28mm, quantity=30,
        location=loc_upstairs_cab2
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Panzer IV", game=game_flames,
        scale=scale_15mm, quantity=5,
        location=loc_upstairs_cab2
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Norman Knights", game=game_saga,
        scale=scale_28mm, quantity=20,
        location=loc_upstairs_cab3
    ).save()

    # ─────────────────────────────────────────
    # Terrains
    # ─────────────────────────────────────────
    Terrain(
        association=assoc, category=cat_terrain,
        type="Ruined Building", game=game_bolt_action,
        scale=scale_28mm, theater="Western Europe",
        location=loc_downstairs_cab1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Palm Trees Set", game=game_flames,
        scale=scale_15mm, theater="North Africa",
        location=loc_downstairs_cab1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Stone Walls", game=game_black_powder,
        scale=scale_28mm, theater="Europe",
        location=loc_downstairs_cab1
    ).save()

    # ─────────────────────────────────────────
    # Rulebooks
    # ─────────────────────────────────────────
    Rulebook(
        association=assoc, category=cat_rulebook,
        name="Bolt Action Core Rulebook", game=game_bolt_action,
        supplement=False, quantity=2,
        location=loc_upstairs_cab3
    ).save()

    Rulebook(
        association=assoc, category=cat_rulebook,
        name="Tank War", game=game_bolt_action,
        supplement=True, quantity=1,
        location=loc_upstairs_cab3
    ).save()

    Rulebook(
        association=assoc, category=cat_rulebook,
        name="Chain of Command Rulebook", game=game_chain_of_cmd,
        supplement=False, quantity=1,
        location=loc_upstairs_cab3
    ).save()

    # ─────────────────────────────────────────
    # Board Games
    # ─────────────────────────────────────────
    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Memoir 44", universe="World War II",
        location=loc_downstairs_cab2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Commands & Colors Ancients", universe="Antiquity",
        location=loc_downstairs_cab2
    ).save()

    # ─────────────────────────────────────────
    # Books
    # ─────────────────────────────────────────
    Book(
        association=assoc, category=cat_book,
        name="Overlord - The D-Day Landings", universe="World War II",
        period="1944", location=loc_downstairs_cab3
    ).save()

    Book(
        association=assoc, category=cat_book,
        name="The Art of War", universe="Antiquity",
        period="500 BC", location=loc_downstairs_cab3
    ).save()

    # ─────────────────────────────────────────
    # Equipment
    # ─────────────────────────────────────────
    Equipment(
        association=assoc, category=cat_equipment,
        type="Folding Table", quantity=6,
        location=loc_downstairs_cab1
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Extension Cord", quantity=2,
        location=loc_downstairs_cab1
    ).save()

    # ─────────────────────────────────────────
    # Consumables
    # ─────────────────────────────────────────
    Consumable(
        association=assoc, category=cat_consumable,
        type="Plastic Cups", unit="U", quantity=200,
        location=loc_downstairs_cab2
    ).save()

    Consumable(
        association=assoc, category=cat_consumable,
        type="Paper Napkins", unit="U", quantity=150,
        location=loc_downstairs_cab2
    ).save()

    print("✅ Seed completed successfully!")


if __name__ == "__main__":
    seed()
