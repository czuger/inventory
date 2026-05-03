import pytest

from inventory.api.app import create_app
from inventory.db.association import Association
from inventory.db.board_game import BoardGame
from inventory.db.book import Book
from inventory.db.borrowing import Borrowing
from inventory.db.duplicate_link import DuplicateLink
from inventory.db.consumable import Consumable
from inventory.db.equipment import Equipment
from inventory.db.game import Game
from inventory.db.location import Location
from inventory.db.miniature import Miniature
from inventory.db.rulebook import Rulebook
from inventory.db.tablecloth import Tablecloth
from inventory.db.terrain import Terrain
from inventory.db.user import User

ALL_ITEM_MODELS = [Miniature, Terrain, Tablecloth, Rulebook, BoardGame, Book, Equipment, Consumable]


@pytest.fixture(scope='session')
def app():
    a = create_app(test=True)
    a.config['TESTING'] = True
    return a


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(scope='session')
def db(app):
    assoc = Association(name='Test Asso', slug='test').save()
    game  = Game(name='Test Game').save()
    loc   = Location(association=assoc, room='Room 1').save()
    admin = User(discord_id='100', username='admin_user', is_admin=True).save()
    user  = User(discord_id='200', username='plain_user', is_admin=False).save()
    yield dict(assoc=assoc, game=game, loc=loc, admin=admin, user=user)
    for Model in ALL_ITEM_MODELS + [Borrowing, DuplicateLink, Location, User, Game, Association]:
        Model.objects.delete()


@pytest.fixture(autouse=True)
def clean_items(db):
    yield
    for Model in ALL_ITEM_MODELS + [Borrowing, DuplicateLink]:
        Model.objects.delete()


def login(client, user):
    with client.session_transaction() as sess:
        sess['user_id'] = str(user.id)


def logout(client):
    with client.session_transaction() as sess:
        sess.pop('user_id', None)
