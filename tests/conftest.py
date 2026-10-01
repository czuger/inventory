import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete as sql_delete
from sqlalchemy import func, select

from inventory.api.app import create_app
from inventory.db.base import db as sql
from inventory.db.models import (
    Association, BoardGame, Book, Borrowing, Consumable, DuplicateLink, Equipment, Game, LegacyObjectId, Location,
    Miniature, Rulebook, Tablecloth, Terrain, User,
)
from inventory.libs.initialization import find_project_root

ALL_ITEM_MODELS = [Miniature, Terrain, Tablecloth, Rulebook, BoardGame, Book, Equipment, Consumable]


def alembic_config(url):
    cfg = Config(os.path.join(find_project_root(), 'alembic.ini'))
    cfg.set_main_option('sqlalchemy.url', url)
    return cfg


@pytest.fixture(scope='session')
def app():
    a = create_app(test=True)
    a.config['TESTING'] = True
    # A fresh data/inventory_test.sqlite3 for every run, built by the migrations
    # themselves rather than create_all(), so the suite also proves they work.
    url = a.config['SQLALCHEMY_DATABASE_URI']
    path = url.removeprefix('sqlite:///')
    for suffix in ('', '-wal', '-shm'):
        if os.path.exists(path + suffix):
            os.remove(path + suffix)
    command.upgrade(alembic_config(url), 'head')
    return a


@pytest.fixture
def client(app):
    return app.test_client()


# pytest-flask pushes a request context around every test, so tests, fixtures and
# the requests the test client makes all share one app context — and therefore
# one SQLAlchemy session. Only session-scoped fixtures need their own context.

def save(obj):
    sql.session.add(obj)
    sql.session.commit()
    return obj


def reload(obj):
    sql.session.refresh(obj)


def remove(obj):
    sql.session.delete(obj)
    sql.session.commit()


def count(Model, **filters):
    return sql.session.scalar(select(func.count()).select_from(Model).filter_by(**filters))


def first(Model, **filters):
    return sql.session.scalar(select(Model).filter_by(**filters).order_by(Model.id).limit(1))


def _delete_all(Models):
    for Model in Models:
        sql.session.execute(sql_delete(Model))
    sql.session.commit()


@pytest.fixture(scope='session')
def _seed(app):
    with app.app_context():
        assoc = save(Association(name='Test Asso', slug='test'))
        game  = save(Game(name='Test Game'))
        loc   = save(Location(association=assoc, room='Room 1'))
        admin = save(User(discord_id='100', username='admin_user', is_admin=True))
        user  = save(User(discord_id='200', username='plain_user', is_admin=False))
        ids = dict(assoc=(Association, assoc.id), game=(Game, game.id), loc=(Location, loc.id),
                   admin=(User, admin.id), user=(User, user.id))
    yield ids
    with app.app_context():
        # Children before parents: foreign keys are enforced.
        _delete_all(ALL_ITEM_MODELS + [Borrowing, DuplicateLink, LegacyObjectId, Location, User, Game, Association])


@pytest.fixture
def db(_seed):
    """The seeded rows, loaded into this test's session."""
    return {key: sql.session.get(Model, id_) for key, (Model, id_) in _seed.items()}


@pytest.fixture(autouse=True)
def clean_items(db):
    yield
    sql.session.rollback()
    _delete_all(ALL_ITEM_MODELS + [Borrowing, DuplicateLink, LegacyObjectId])


def login(client, user):
    with client.session_transaction() as sess:
        sess['user_id'] = user.id


def logout(client):
    with client.session_transaction() as sess:
        sess.pop('user_id', None)
