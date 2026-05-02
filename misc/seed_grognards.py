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

connect(
    db=config['mongo']['database'],
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


def clear():
    for model in [Tablecloth, Terrain, Miniature, Rulebook, BoardGame, Equipment, Consumable,
                  Location, TableclothSize, Scale, Game, Category, Association]:
        model.objects.delete()


def seed():
    clear()

    # ─────────────────────────────────────────
    # Association
    # ─────────────────────────────────────────
    assoc = get_or_create(Association, name="Les Grognards du Dimanche")

    # ─────────────────────────────────────────
    # Categories
    # ─────────────────────────────────────────
    cat_tablecloth = get_or_create(Category, name="Tablecloth")
    cat_miniature  = get_or_create(Category, name="Miniature")
    cat_terrain    = get_or_create(Category, name="Terrain")
    cat_rulebook   = get_or_create(Category, name="Rulebook")
    cat_boardgame  = get_or_create(Category, name="Board Game")
    cat_book       = get_or_create(Category, name="Book")
    cat_equipment  = get_or_create(Category, name="Equipment")
    cat_consumable = get_or_create(Category, name="Consumable")

    # ─────────────────────────────────────────
    # Games
    # ─────────────────────────────────────────
    game_generic   = get_or_create(Game, name="Generic")
    game_saga      = get_or_create(Game, name="SAGA")
    game_guildball = get_or_create(Game, name="Guildball")
    game_malifaux  = get_or_create(Game, name="Malifaux")
    game_starwars  = get_or_create(Game, name="Star Wars")
    game_adg       = get_or_create(Game, name="Art de la Guerre")
    game_armada    = get_or_create(Game, name="Star Wars Armada")
    game_sda       = get_or_create(Game, name="Seigneur des Anneaux")
    game_congo     = get_or_create(Game, name="CONGO")
    game_bolt      = get_or_create(Game, name="Bolt Action")
    game_fow       = get_or_create(Game, name="Flames of War")
    game_sails     = get_or_create(Game, name="Sails of Glory")
    game_jugula    = get_or_create(Game, name="Jugula")
    game_briskars  = get_or_create(Game, name="Briskars")

    # ─────────────────────────────────────────
    # Scales
    # ─────────────────────────────────────────
    scale_70mm  = get_or_create(Scale, value="70mm")
    scale_28mm  = get_or_create(Scale, value="28mm")
    scale_15mm  = get_or_create(Scale, value="15mm")
    scale_mixed = get_or_create(Scale, value="Mixte")

    # ─────────────────────────────────────────
    # Tablecloth Sizes
    # ─────────────────────────────────────────
    size_120x180 = get_or_create(TableclothSize, size_cm="120x180", size_inches='48"x72"')
    size_120x90  = get_or_create(TableclothSize, size_cm="120x90",  size_inches='48"x36"')
    size_90x90   = get_or_create(TableclothSize, size_cm="90x90",   size_inches='36"x36"')
    size_120x120 = get_or_create(TableclothSize, size_cm="120x120", size_inches='48"x48"')
    size_120x80  = get_or_create(TableclothSize, size_cm="120x80",  size_inches='48"x32"')
    size_unknown = get_or_create(TableclothSize, size_cm="?x?",     size_inches='?x?')

    # ─────────────────────────────────────────
    # Locations
    #   Grande salle: placard 1 porte, placard 2 portes, pièce 1, vitrine 1, vitrine 2
    #   Petite salle: pièce 2, armoire 1, armoire 2
    # ─────────────────────────────────────────
    loc_gs_pl1  = get_or_create(Location, association=assoc, room="Grande salle", spot="Placard 1 porte")
    loc_gs_pl2  = get_or_create(Location, association=assoc, room="Grande salle", spot="Placard 2 portes")
    loc_gs_p1   = get_or_create(Location, association=assoc, room="Grande salle", spot="Pièce 1")
    loc_gs_v1   = get_or_create(Location, association=assoc, room="Grande salle", spot="Vitrine 1")
    loc_gs_v2   = get_or_create(Location, association=assoc, room="Grande salle", spot="Vitrine 2")
    loc_ps_p2   = get_or_create(Location, association=assoc, room="Petite salle", spot="Pièce 2")
    loc_ps_arm1 = get_or_create(Location, association=assoc, room="Petite salle", spot="Armoire 1")
    loc_ps_arm2 = get_or_create(Location, association=assoc, room="Petite salle", spot="Armoire 2")

    # ─────────────────────────────────────────
    # Tablecloths  (section 1.1.1 — source: Nappes.tsv)
    # ─────────────────────────────────────────

    # 1.1.1.1 — nappes floquées (1,2x1,8) ×23
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe floquée", material="textured", game=game_generic,
        number=23, size=size_120x180, location=loc_ps_arm1
    ).save()

    # 1.1.1.2 — nappes tissu (1,2x1,8) ×6
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe tissu", material="cloth", game=game_generic,
        number=6, size=size_120x180, location=loc_ps_arm1
    ).save()

    # 1.1.1.3 — nappes mousse (1,2x0,9) ×25 — SAGA
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe mousse", material="mousepad (neoprene)", game=game_saga,
        number=25, size=size_120x90, location=loc_gs_pl1
    ).save()

    # 1.1.1.4 — nappes mousse (0,9x0,9) ×8 — Guildball
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe mousse", material="mousepad (neoprene)", game=game_guildball,
        number=8, size=size_90x90, location=loc_gs_pl1
    ).save()

    # 1.1.1.5 — nappes mousse (0,9x0,9) ×2 — Malifaux, placard 1 porte
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe mousse", material="mousepad (neoprene)", game=game_malifaux,
        number=2, size=size_90x90, remarks="en housse", location=loc_gs_pl1
    ).save()

    # 1.1.1.5 — nappes mousse (0,9x0,9) ×2 — Malifaux, pièce 1
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe mousse", material="mousepad (neoprene)", game=game_malifaux,
        number=2, size=size_90x90, remarks="en housse", location=loc_gs_p1
    ).save()

    # 1.1.1.6 — nappes mousse (1,2x1,8) ×1 — désert
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe mousse désert", material="mousepad (neoprene)", game=game_generic,
        number=1, size=size_120x180, location=loc_gs_pl1
    ).save()

    # 1.1.1.6 — nappes mousse (1,2x1,8) ×1 — glace
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe mousse glace", material="mousepad (neoprene)", game=game_generic,
        number=1, size=size_120x180, location=loc_gs_pl1
    ).save()

    # 1.1.1.6 — nappes mousse (1,2x1,8) ×1 — feu
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe mousse feu", material="mousepad (neoprene)", game=game_generic,
        number=1, size=size_120x180, location=loc_gs_pl1
    ).save()

    # 1.1.1.7 — nappes mousse (1,2x1,2) ×4 — désert+plage
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe mousse désert/plage", material="mousepad (neoprene)", game=game_generic,
        number=4, size=size_120x120, location=loc_gs_p1
    ).save()

    # 1.1.1.8 — nappes mousse (1,2x1,8) ×2 — Star Wars
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe mousse Star Wars", material="mousepad (neoprene)", game=game_starwars,
        number=2, size=size_120x180, location=loc_gs_p1
    ).save()

    # 1.1.1.9 — nappes ADG (1,2x0,8) ×1 mousepad — perdues dans la masse
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe ADG", material="mousepad (neoprene)", game=game_adg,
        number=1, size=size_120x80, remarks="perdues dans la masse", location=loc_gs_pl1
    ).save()

    # 1.1.1.9 — nappes ADG (1,2x0,8) ×4 texturées — perdues dans la masse
    Tablecloth(
        association=assoc, category=cat_tablecloth,
        type="Nappe ADG", material="textured", game=game_adg,
        number=4, size=size_120x80, remarks="perdues dans la masse", location=loc_gs_pl1
    ).save()

    # ─────────────────────────────────────────
    # Terrain  (sections 1.1.2 + 1.2)
    # ─────────────────────────────────────────

    # Plaques modulaires (1.1.2)
    Terrain(
        association=assoc, category=cat_terrain,
        type="Plaques mélaminées peintes/floquées 50x50 (avec rivière)", game=game_generic,
        scale=scale_mixed, location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Plaques polystyrène floquées 60x60 – steppe", game=game_generic,
        scale=scale_mixed, location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Plaques polystyrène floquées 60x60 – plage", game=game_generic,
        scale=scale_mixed, location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Plaques polystyrène floquées 60x60 – neige", game=game_generic,
        scale=scale_mixed, location=loc_gs_p1
    ).save()

    # Décors 15mm (1.2.1)
    Terrain(
        association=assoc, category=cat_terrain,
        type="Bâtiments est-européens", game=game_generic,
        scale=scale_15mm, theater="Est Europe", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Bâtiments ruines", game=game_generic,
        scale=scale_15mm, location=loc_gs_p1
    ).save()

    # Décors 28mm (1.2.2)
    Terrain(
        association=assoc, category=cat_terrain,
        type="Bâtiments médiévaux (panières)", game=game_generic,
        scale=scale_28mm, theater="Médiéval", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Murs (1,5m)", game=game_generic,
        scale=scale_28mm, location=loc_gs_v1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Temple antique", game=game_generic,
        scale=scale_28mm, theater="Antiquité", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Temple grec", game=game_generic,
        scale=scale_28mm, theater="Antiquité", location=loc_gs_v1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Temple Gondor", game=game_sda,
        scale=scale_28mm, theater="Terre du Milieu", location=loc_gs_v1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Tour féodale", game=game_generic,
        scale=scale_28mm, theater="Médiéval", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Tour médiévale", game=game_generic,
        scale=scale_28mm, theater="Médiéval", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Maisons 20e siècle + routes", game=game_bolt,
        scale=scale_28mm, theater="XXe siècle", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Mur de la mine", game=game_generic,
        scale=scale_28mm, location=loc_gs_v1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Tombeau de Balin", game=game_sda,
        scale=scale_28mm, theater="Terre du Milieu", location=loc_gs_v2
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Arène cirque Jugula", game=game_jugula,
        scale=scale_28mm, theater="Antiquité", location=loc_gs_v2
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Décors désert (2 boîtes)", game=game_generic,
        scale=scale_28mm, theater="Désert", location=loc_gs_pl2
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Décors Asie", game=game_generic,
        scale=scale_28mm, theater="Asie", location=loc_gs_pl2
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Arbres (dont sapins)", game=game_generic,
        scale=scale_mixed, location=loc_gs_pl1
    ).save()

    # Bolt Action décors (1.2.4)
    Terrain(
        association=assoc, category=cat_terrain,
        type="Table Stalingrad", game=game_bolt,
        scale=scale_28mm, theater="Front Est", location=loc_gs_pl2
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Table France occupée", game=game_bolt,
        scale=scale_28mm, theater="Ouest Europe", location=loc_gs_pl2
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Table maisons allemagne + gare", game=game_bolt,
        scale=scale_28mm, theater="Allemagne", location=loc_gs_pl2
    ).save()

    # Décors +30mm (1.2.3)
    Terrain(
        association=assoc, category=cat_terrain,
        type="Décors Malifaux", game=game_malifaux,
        scale=scale_28mm, location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Décors Briskars", game=game_briskars,
        scale=scale_28mm, location=loc_gs_pl2
    ).save()

    Terrain(
        association=assoc, category=cat_terrain,
        type="Fig Symbiotique", game=game_briskars,
        scale=scale_28mm, location=loc_gs_v1
    ).save()

    # ─────────────────────────────────────────
    # Miniatures  (section 1.3)
    # ─────────────────────────────────────────

    # Star Wars Armada (1.3.1)
    Miniature(
        association=assoc, category=cat_miniature,
        type="Armada – Alliance & Empire (2 cartons + 1 panière)", game=game_armada,
        scale=scale_mixed, quantity=3, location=loc_gs_p1
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Armada – Conflit Corélien (campagne)", game=game_armada,
        scale=scale_mixed, quantity=1, location=loc_gs_p1
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Armada – Destroyer stellaire", game=game_armada,
        scale=scale_mixed, quantity=1, location=loc_gs_p1
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Armada – Phoenix Home", game=game_armada,
        scale=scale_mixed, quantity=1, location=loc_gs_p1
    ).save()

    # Seigneur des Anneaux (1.3.2)
    Miniature(
        association=assoc, category=cat_miniature,
        type="Uruk-aï", game=game_sda,
        scale=scale_28mm, quantity=3, location=loc_gs_v1
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Gobelins", game=game_sda,
        scale=scale_28mm, quantity=1, location=loc_gs_v1
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Trolls", game=game_sda,
        scale=scale_28mm, quantity=2, location=loc_gs_v1
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Haradrims (dont 1 Mamelik)", game=game_sda,
        scale=scale_28mm, quantity=40, location=loc_gs_v2
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Rohans", game=game_sda,
        scale=scale_28mm, quantity=3, location=loc_gs_v1
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Elfes", game=game_sda,
        scale=scale_28mm, quantity=32, location=loc_gs_v1
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Aventuriers", game=game_sda,
        scale=scale_28mm, quantity=20, location=loc_gs_v1
    ).save()

    # SAGA (1.3.3)
    Miniature(
        association=assoc, category=cat_miniature,
        type="Age de la Magie – squelettes", game=game_saga,
        scale=scale_28mm, quantity=9, location=loc_gs_v2
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Age des Invasions – piétons et cavaliers", game=game_saga,
        scale=scale_28mm, quantity=37, location=loc_gs_v2
    ).save()

    # CONGO (1.3.4)
    Miniature(
        association=assoc, category=cat_miniature,
        type="Figurines + décors CONGO", game=game_congo,
        scale=scale_28mm, quantity=60, location=loc_gs_v1
    ).save()

    # Bolt Action (1.3.5)
    Miniature(
        association=assoc, category=cat_miniature,
        type="Battlegroup USA (en guêtres) + M4A1 + half-track", game=game_bolt,
        scale=scale_28mm, quantity=62, location=loc_gs_v1
    ).save()

    # Flames of War (1.3.6)
    Miniature(
        association=assoc, category=cat_miniature,
        type="Compagnie chars USA (à monter)", game=game_fow,
        scale=scale_15mm, quantity=1, location=loc_gs_p1
    ).save()

    Miniature(
        association=assoc, category=cat_miniature,
        type="Maquettes FOW", game=game_fow,
        scale=scale_15mm, quantity=2, location=loc_gs_p1
    ).save()

    # ─────────────────────────────────────────
    # Rulebooks  (section 1.4.2)
    # ─────────────────────────────────────────
    Rulebook(
        association=assoc, category=cat_rulebook,
        name="SAGA V2", game=game_saga,
        supplement=False, quantity=1, location=loc_gs_p1
    ).save()

    Rulebook(
        association=assoc, category=cat_rulebook,
        name="SAGA – Age de la Magie", game=game_saga,
        supplement=True, quantity=1, location=loc_gs_p1
    ).save()

    Rulebook(
        association=assoc, category=cat_rulebook,
        name="SAGA – Age d'Hannibal", game=game_saga,
        supplement=True, quantity=1, location=loc_gs_p1
    ).save()

    Rulebook(
        association=assoc, category=cat_rulebook,
        name="SAGA – Croissant & Croix", game=game_saga,
        supplement=True, quantity=1, location=loc_gs_p1
    ).save()

    Rulebook(
        association=assoc, category=cat_rulebook,
        name="CONGO", game=game_congo,
        supplement=False, quantity=1, location=loc_gs_v1
    ).save()

    Rulebook(
        association=assoc, category=cat_rulebook,
        name="Au contact", game=game_generic,
        supplement=False, quantity=1, location=loc_ps_arm1
    ).save()

    Rulebook(
        association=assoc, category=cat_rulebook,
        name="Field of Glory V2", game=game_generic,
        supplement=False, quantity=3, location=loc_ps_arm1
    ).save()

    Rulebook(
        association=assoc, category=cat_rulebook,
        name="V for Victory", game=game_generic,
        supplement=False, quantity=1, location=loc_ps_arm1
    ).save()

    Rulebook(
        association=assoc, category=cat_rulebook,
        name="Art de la Guerre V4", game=game_adg,
        supplement=False, quantity=2, location=loc_ps_arm2
    ).save()

    Rulebook(
        association=assoc, category=cat_rulebook,
        name="Sails of Glory", game=game_sails,
        supplement=False, quantity=1, location=loc_ps_p2
    ).save()

    # ─────────────────────────────────────────
    # Board Games  (section 1.4.1)
    # ─────────────────────────────────────────
    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Guerre de l'Anneau", universe="Terre du Milieu",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Britannia", universe="Antiquité / Médiéval",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="An Mil", universe="Médiéval",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Barbe Noire",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Empire",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Diplomacy",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Power",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Bounty Hunter – Shoot at the Saloon", universe="Far West",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Aces of Aces", universe="WWI",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Wanted",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Strike",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Formule D", universe="Automobile",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Battle for Britain – Blood Red Skies", universe="WWII",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Handicap Race",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category=cat_boardgame,
        name="Sails of Glory (4 boîtes bateaux)", universe="Âge de la voile",
        location=loc_ps_p2
    ).save()

    # ─────────────────────────────────────────
    # Equipment  (section 1.4.appareils + 1.5)
    # ─────────────────────────────────────────
    Equipment(
        association=assoc, category=cat_equipment,
        type="Machine à café (3 filtres + 1 dosettes)", quantity=4,
        location=loc_gs_p1
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Thermos (2 café + 1 eau chaude)", quantity=3,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Plastifieuse", quantity=1,
        location=loc_ps_arm1
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Rétroprojecteur", quantity=1,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Rallonge électrique (1×20m + 1×25m)", quantity=2,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Multiprise", quantity=3,
        location=loc_gs_p1
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Radio CD", quantity=1,
        location=loc_gs_v2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Caméra Sony FDR-AX43", quantity=1,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Pied caméra Neewer 177cm", quantity=1,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Lumières + pieds", quantity=2,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Carte SSD", quantity=3,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Caissette avec clé", quantity=3,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Épée bâtarde en acier (Espagne)", quantity=1,
        location=loc_gs_p1
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Vitrine tout en verre", quantity=1,
        location=loc_gs_v2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Coffre à roulettes (plaques 120cm)", quantity=1,
        location=loc_gs_v2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Mètre-ruban rouge 2m", quantity=1,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Dés à 6 faces", quantity=90,
        location=loc_gs_v1
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Règle métallique 60cm", quantity=1,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Ciseaux à poulets magnétiques", quantity=2,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Pintes de bière", quantity=24,
        location=loc_gs_v2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Marteau", quantity=1,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Balai", quantity=1,
        location=loc_gs_v2
    ).save()

    Equipment(
        association=assoc, category=cat_equipment,
        type="Poubelle avec tri", quantity=2,
        location=loc_gs_p1
    ).save()

    # ─────────────────────────────────────────
    # Consumables  (section 2)
    # ─────────────────────────────────────────
    Consumable(
        association=assoc, category=cat_consumable,
        type="Barres chocolatées", unit="kg", quantity=1,
        location=loc_gs_p1
    ).save()

    Consumable(
        association=assoc, category=cat_consumable,
        type="Café", unit="kg", quantity=2,
        location=loc_gs_p1
    ).save()

    Consumable(
        association=assoc, category=cat_consumable,
        type="Jus d'orange", unit="L", quantity=3,
        location=loc_gs_p1
    ).save()

    Consumable(
        association=assoc, category=cat_consumable,
        type="Filtres à café (boîtes de 80)", unit="boîte", quantity=3,
        location=loc_gs_p1
    ).save()

    print("✅ Seed Grognards terminé avec succès !")


if __name__ == "__main__":
    seed()
