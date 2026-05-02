from mongoengine import *

from inventory.db.association import Association
from inventory.db.board_game import BoardGame
from inventory.db.borrowing import Borrowing
from inventory.db.consumable import Consumable
from inventory.db.equipment import Equipment
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.miniature import Miniature
from inventory.db.rulebook import Rulebook
from inventory.db.tablecloth import Tablecloth
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
    for model in [Borrowing, Tablecloth, Terrain, Miniature, Rulebook, BoardGame, Equipment,
                  Consumable, Location, Game, Association]:
        model.objects.delete()


def seed():
    clear()

    # ─────────────────────────────────────────
    # Association
    # ─────────────────────────────────────────
    assoc = get_or_create(Association, name="Les Grognards d'Alsace", slug="grognards")

    # ─────────────────────────────────────────
    # Games
    # ─────────────────────────────────────────
    game_generic = get_or_create(Game, name="Generic")
    game_saga = get_or_create(Game, name="SAGA")
    game_guildball = get_or_create(Game, name="Guildball")
    game_malifaux = get_or_create(Game, name="Malifaux")
    game_starwars = get_or_create(Game, name="Star Wars")
    game_adg = get_or_create(Game, name="Art de la Guerre")
    game_armada = get_or_create(Game, name="Star Wars Armada")
    game_sda = get_or_create(Game, name="Seigneur des Anneaux")
    game_congo = get_or_create(Game, name="CONGO")
    game_bolt = get_or_create(Game, name="Bolt Action")
    game_fow = get_or_create(Game, name="Flames of War")
    game_sails = get_or_create(Game, name="Sails of Glory")
    game_jugula = get_or_create(Game, name="Jugula")
    game_briskars = get_or_create(Game, name="Briskars")

    # ─────────────────────────────────────────
    # Locations
    #   Grande salle: placard 1 porte, placard 2 portes, pièce 1, vitrine 1, vitrine 2
    #   Petite salle: pièce 2, armoire 1, armoire 2
    # ─────────────────────────────────────────
    loc_gs_pl1 = get_or_create(Location, association=assoc, room="Grande salle", spot="Placard 1 porte")
    loc_gs_pl2 = get_or_create(Location, association=assoc, room="Grande salle", spot="Placard 2 portes")
    loc_gs_p1 = get_or_create(Location, association=assoc, room="Grande salle", spot="Pièce 1")
    loc_gs_v1 = get_or_create(Location, association=assoc, room="Grande salle", spot="Vitrine 1")
    loc_gs_v2 = get_or_create(Location, association=assoc, room="Grande salle", spot="Vitrine 2")
    loc_ps_p2 = get_or_create(Location, association=assoc, room="Petite salle", spot="Pièce 2")
    loc_ps_arm1 = get_or_create(Location, association=assoc, room="Petite salle", spot="Armoire 1")
    loc_ps_arm2 = get_or_create(Location, association=assoc, room="Petite salle", spot="Armoire 2")

    # ─────────────────────────────────────────
    # Tablecloths  (section 1.1.1 — source: Nappes.tsv)
    # ─────────────────────────────────────────

    # 1.1.1.1 — nappes floquées (1,2x1,8) ×23
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe floquée", material="textured", game=game_generic,
        quantity=23, size="120x180", location=loc_ps_arm1
    ).save()

    # 1.1.1.2 — nappes tissu (1,2x1,8) ×6
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe tissu", material="cloth", game=game_generic,
        quantity=6, size="120x180", location=loc_ps_arm1
    ).save()

    # 1.1.1.3 — nappes mousse (1,2x0,9) ×25 — SAGA
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe mousse", material="mousepad (neoprene)", game=game_saga,
        quantity=25, size="120x90", location=loc_gs_pl1
    ).save()

    # 1.1.1.4 — nappes mousse (0,9x0,9) ×8 — Guildball
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe mousse", material="mousepad (neoprene)", game=game_guildball,
        quantity=8, size="90x90", location=loc_gs_pl1
    ).save()

    # 1.1.1.5 — nappes mousse (0,9x0,9) ×2 — Malifaux, placard 1 porte
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe mousse", material="mousepad (neoprene)", game=game_malifaux,
        quantity=2, size="90x90", remarks="en housse", location=loc_gs_pl1
    ).save()

    # 1.1.1.5 — nappes mousse (0,9x0,9) ×2 — Malifaux, pièce 1
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe mousse", material="mousepad (neoprene)", game=game_malifaux,
        quantity=2, size="90x90", remarks="en housse", location=loc_gs_p1
    ).save()

    # 1.1.1.6 — nappes mousse (1,2x1,8) ×1 — désert
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe mousse désert", material="mousepad (neoprene)", game=game_generic,
        quantity=1, size="120x180", location=loc_gs_pl1
    ).save()

    # 1.1.1.6 — nappes mousse (1,2x1,8) ×1 — glace
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe mousse glace", material="mousepad (neoprene)", game=game_generic,
        quantity=1, size="120x180", location=loc_gs_pl1
    ).save()

    # 1.1.1.6 — nappes mousse (1,2x1,8) ×1 — feu
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe mousse feu", material="mousepad (neoprene)", game=game_generic,
        quantity=1, size="120x180", location=loc_gs_pl1
    ).save()

    # 1.1.1.7 — nappes mousse (1,2x1,2) ×4 — désert+plage
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe mousse désert/plage", material="mousepad (neoprene)", game=game_generic,
        quantity=4, size="120x120", location=loc_gs_p1
    ).save()

    # 1.1.1.8 — nappes mousse (1,2x1,8) ×2 — Star Wars
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe mousse Star Wars", material="mousepad (neoprene)", game=game_starwars,
        quantity=2, size="120x180", location=loc_gs_p1
    ).save()

    # 1.1.1.9 — nappes ADG (1,2x0,8) ×1 mousepad — perdues dans la masse
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe ADG", material="mousepad (neoprene)", game=game_adg,
        quantity=1, size="120x80", remarks="perdues dans la masse", location=loc_gs_pl1
    ).save()

    # 1.1.1.9 — nappes ADG (1,2x0,8) ×4 texturées — perdues dans la masse
    Tablecloth(
        association=assoc, category="Tablecloth",
        type="Nappe ADG", material="textured", game=game_adg,
        quantity=4, size="120x80", remarks="perdues dans la masse", location=loc_gs_pl1
    ).save()

    # ─────────────────────────────────────────
    # Terrain  (sections 1.1.2 + 1.2)
    # ─────────────────────────────────────────

    # Plaques modulaires (1.1.2)
    Terrain(
        association=assoc, category="Terrain",
        type="Plaques mélaminées peintes/floquées 50x50 (avec rivière)", game=game_generic,
        scale="Mixte", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Plaques polystyrène floquées 60x60 – steppe", game=game_generic,
        scale="Mixte", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Plaques polystyrène floquées 60x60 – plage", game=game_generic,
        scale="Mixte", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Plaques polystyrène floquées 60x60 – neige", game=game_generic,
        scale="Mixte", location=loc_gs_p1
    ).save()

    # Décors 15mm (1.2.1)
    Terrain(
        association=assoc, category="Terrain",
        type="Bâtiments est-européens", game=game_generic,
        scale="15mm", theater="Est Europe", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Bâtiments ruines", game=game_generic,
        scale="15mm", location=loc_gs_p1
    ).save()

    # Décors 28mm (1.2.2)
    Terrain(
        association=assoc, category="Terrain",
        type="Bâtiments médiévaux (panières)", game=game_generic,
        scale="28mm", theater="Médiéval", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Murs (1,5m)", game=game_generic,
        scale="28mm", location=loc_gs_v1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Temple antique", game=game_generic,
        scale="28mm", theater="Antiquité", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Temple grec", game=game_generic,
        scale="28mm", theater="Antiquité", location=loc_gs_v1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Temple Gondor", game=game_sda,
        scale="28mm", theater="Terre du Milieu", location=loc_gs_v1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Tour féodale", game=game_generic,
        scale="28mm", theater="Médiéval", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Tour médiévale", game=game_generic,
        scale="28mm", theater="Médiéval", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Maisons 20e siècle + routes", game=game_bolt,
        scale="28mm", theater="XXe siècle", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Mur de la mine", game=game_generic,
        scale="28mm", location=loc_gs_v1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Tombeau de Balin", game=game_sda,
        scale="28mm", theater="Terre du Milieu", location=loc_gs_v2
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Arène cirque Jugula", game=game_jugula,
        scale="28mm", theater="Antiquité", location=loc_gs_v2
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Décors désert (2 boîtes)", game=game_generic,
        scale="28mm", theater="Désert", location=loc_gs_pl2
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Décors Asie", game=game_generic,
        scale="28mm", theater="Asie", location=loc_gs_pl2
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Arbres (dont sapins)", game=game_generic,
        scale="Mixte", location=loc_gs_pl1
    ).save()

    # Bolt Action décors (1.2.4)
    Terrain(
        association=assoc, category="Terrain",
        type="Table Stalingrad", game=game_bolt,
        scale="28mm", theater="Front Est", location=loc_gs_pl2
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Table France occupée", game=game_bolt,
        scale="28mm", theater="Ouest Europe", location=loc_gs_pl2
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Table maisons allemagne + gare", game=game_bolt,
        scale="28mm", theater="Allemagne", location=loc_gs_pl2
    ).save()

    # Décors +30mm (1.2.3)
    Terrain(
        association=assoc, category="Terrain",
        type="Décors Malifaux", game=game_malifaux,
        scale="28mm", location=loc_gs_p1
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Décors Briskars", game=game_briskars,
        scale="28mm", location=loc_gs_pl2
    ).save()

    Terrain(
        association=assoc, category="Terrain",
        type="Fig Symbiotique", game=game_briskars,
        scale="28mm", location=loc_gs_v1
    ).save()

    # ─────────────────────────────────────────
    # Miniatures  (section 1.3)
    # ─────────────────────────────────────────

    # Star Wars Armada (1.3.1)
    Miniature(
        association=assoc, category="Miniature",
        type="Armada – Alliance & Empire (2 cartons + 1 panière)", game=game_armada,
        scale="Mixte", quantity=3, location=loc_gs_p1
    ).save()

    Miniature(
        association=assoc, category="Miniature",
        type="Armada – Conflit Corélien (campagne)", game=game_armada,
        scale="Mixte", quantity=1, location=loc_gs_p1
    ).save()

    Miniature(
        association=assoc, category="Miniature",
        type="Armada – Destroyer stellaire", game=game_armada,
        scale="Mixte", quantity=1, location=loc_gs_p1
    ).save()

    Miniature(
        association=assoc, category="Miniature",
        type="Armada – Phoenix Home", game=game_armada,
        scale="Mixte", quantity=1, location=loc_gs_p1
    ).save()

    # Seigneur des Anneaux (1.3.2)
    Miniature(
        association=assoc, category="Miniature",
        type="Uruk-aï", game=game_sda,
        scale="28mm", quantity=3, location=loc_gs_v1
    ).save()

    Miniature(
        association=assoc, category="Miniature",
        type="Gobelins", game=game_sda,
        scale="28mm", quantity=1, location=loc_gs_v1
    ).save()

    Miniature(
        association=assoc, category="Miniature",
        type="Trolls", game=game_sda,
        scale="28mm", quantity=2, location=loc_gs_v1
    ).save()

    Miniature(
        association=assoc, category="Miniature",
        type="Haradrims (dont 1 Mamelik)", game=game_sda,
        scale="28mm", quantity=40, location=loc_gs_v2
    ).save()

    Miniature(
        association=assoc, category="Miniature",
        type="Rohans", game=game_sda,
        scale="28mm", quantity=3, location=loc_gs_v1
    ).save()

    Miniature(
        association=assoc, category="Miniature",
        type="Elfes", game=game_sda,
        scale="28mm", quantity=32, location=loc_gs_v1
    ).save()

    Miniature(
        association=assoc, category="Miniature",
        type="Aventuriers", game=game_sda,
        scale="28mm", quantity=20, location=loc_gs_v1
    ).save()

    # SAGA (1.3.3)
    Miniature(
        association=assoc, category="Miniature",
        type="Age de la Magie – squelettes", game=game_saga,
        scale="28mm", quantity=9, location=loc_gs_v2
    ).save()

    Miniature(
        association=assoc, category="Miniature",
        type="Age des Invasions – piétons et cavaliers", game=game_saga,
        scale="28mm", quantity=37, location=loc_gs_v2
    ).save()

    # CONGO (1.3.4)
    Miniature(
        association=assoc, category="Miniature",
        type="Figurines + décors CONGO", game=game_congo,
        scale="28mm", quantity=60, location=loc_gs_v1
    ).save()

    # Bolt Action (1.3.5)
    Miniature(
        association=assoc, category="Miniature",
        type="Battlegroup USA (en guêtres) + M4A1 + half-track", game=game_bolt,
        scale="28mm", quantity=62, location=loc_gs_v1
    ).save()

    # Flames of War (1.3.6)
    Miniature(
        association=assoc, category="Miniature",
        type="Compagnie chars USA (à monter)", game=game_fow,
        scale="15mm", quantity=1, location=loc_gs_p1
    ).save()

    Miniature(
        association=assoc, category="Miniature",
        type="Maquettes FOW", game=game_fow,
        scale="15mm", quantity=2, location=loc_gs_p1
    ).save()

    # ─────────────────────────────────────────
    # Rulebooks  (section 1.4.2)
    # ─────────────────────────────────────────
    Rulebook(
        association=assoc, category="Rulebook",
        name="SAGA V2", game=game_saga,
        supplement=False, quantity=1, location=loc_gs_p1
    ).save()

    Rulebook(
        association=assoc, category="Rulebook",
        name="SAGA – Age de la Magie", game=game_saga,
        supplement=True, quantity=1, location=loc_gs_p1
    ).save()

    Rulebook(
        association=assoc, category="Rulebook",
        name="SAGA – Age d'Hannibal", game=game_saga,
        supplement=True, quantity=1, location=loc_gs_p1
    ).save()

    Rulebook(
        association=assoc, category="Rulebook",
        name="SAGA – Croissant & Croix", game=game_saga,
        supplement=True, quantity=1, location=loc_gs_p1
    ).save()

    Rulebook(
        association=assoc, category="Rulebook",
        name="CONGO", game=game_congo,
        supplement=False, quantity=1, location=loc_gs_v1
    ).save()

    Rulebook(
        association=assoc, category="Rulebook",
        name="Au contact", game=game_generic,
        supplement=False, quantity=1, location=loc_ps_arm1
    ).save()

    Rulebook(
        association=assoc, category="Rulebook",
        name="Field of Glory V2", game=game_generic,
        supplement=False, quantity=3, location=loc_ps_arm1
    ).save()

    Rulebook(
        association=assoc, category="Rulebook",
        name="V for Victory", game=game_generic,
        supplement=False, quantity=1, location=loc_ps_arm1
    ).save()

    Rulebook(
        association=assoc, category="Rulebook",
        name="Art de la Guerre V4", game=game_adg,
        supplement=False, quantity=2, location=loc_ps_arm2
    ).save()

    Rulebook(
        association=assoc, category="Rulebook",
        name="Sails of Glory", game=game_sails,
        supplement=False, quantity=1, location=loc_ps_p2
    ).save()

    # ─────────────────────────────────────────
    # Board Games  (section 1.4.1)
    # ─────────────────────────────────────────
    BoardGame(
        association=assoc, category="Board Game",
        name="Guerre de l'Anneau", universe="Terre du Milieu",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Britannia", universe="Antiquité / Médiéval",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="An Mil", universe="Médiéval",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Barbe Noire",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Empire",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Diplomacy",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Power",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Bounty Hunter – Shoot at the Saloon", universe="Far West",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Aces of Aces", universe="WWI",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Wanted",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Strike",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Formule D", universe="Automobile",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Battle for Britain – Blood Red Skies", universe="WWII",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Handicap Race",
        location=loc_ps_p2
    ).save()

    BoardGame(
        association=assoc, category="Board Game",
        name="Sails of Glory (4 boîtes bateaux)", universe="Âge de la voile",
        location=loc_ps_p2
    ).save()

    # ─────────────────────────────────────────
    # Equipment  (section 1.4.appareils + 1.5)
    # ─────────────────────────────────────────
    Equipment(
        association=assoc, category="Equipment",
        type="Machine à café (3 filtres + 1 dosettes)", quantity=4,
        location=loc_gs_p1
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Thermos (2 café + 1 eau chaude)", quantity=3,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Plastifieuse", quantity=1,
        location=loc_ps_arm1
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Rétroprojecteur", quantity=1,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Rallonge électrique (1×20m + 1×25m)", quantity=2,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Multiprise", quantity=3,
        location=loc_gs_p1
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Radio CD", quantity=1,
        location=loc_gs_v2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Caméra Sony FDR-AX43", quantity=1,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Pied caméra Neewer 177cm", quantity=1,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Lumières + pieds", quantity=2,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Carte SSD", quantity=3,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Caissette avec clé", quantity=3,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Épée bâtarde en acier (Espagne)", quantity=1,
        location=loc_gs_p1
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Vitrine tout en verre", quantity=1,
        location=loc_gs_v2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Coffre à roulettes (plaques 120cm)", quantity=1,
        location=loc_gs_v2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Mètre-ruban rouge 2m", quantity=1,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Dés à 6 faces", quantity=90,
        location=loc_gs_v1
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Règle métallique 60cm", quantity=1,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Ciseaux à poulets magnétiques", quantity=2,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Pintes de bière", quantity=24,
        location=loc_gs_v2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Marteau", quantity=1,
        location=loc_ps_arm2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Balai", quantity=1,
        location=loc_gs_v2
    ).save()

    Equipment(
        association=assoc, category="Equipment",
        type="Poubelle avec tri", quantity=2,
        location=loc_gs_p1
    ).save()

    # ─────────────────────────────────────────
    # Consumables  (section 2)
    # ─────────────────────────────────────────
    Consumable(
        association=assoc, category="Consumable",
        type="Barres chocolatées", unit="kg", quantity=1,
        location=loc_gs_p1
    ).save()

    Consumable(
        association=assoc, category="Consumable",
        type="Café", unit="kg", quantity=2,
        location=loc_gs_p1
    ).save()

    Consumable(
        association=assoc, category="Consumable",
        type="Jus d'orange", unit="L", quantity=3,
        location=loc_gs_p1
    ).save()

    Consumable(
        association=assoc, category="Consumable",
        type="Filtres à café (boîtes de 80)", unit="boîte", quantity=3,
        location=loc_gs_p1
    ).save()

    print("✅ Seed Grognards terminé avec succès !")


if __name__ == "__main__":
    seed()
