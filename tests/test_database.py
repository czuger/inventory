import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from inventory.db.base import db as sql
from inventory.db.models import Association, LegacyObjectId, Location, Miniature
from tests.conftest import count, login, save


def _pragma(name):
    return sql.session.execute(text(f'PRAGMA {name}')).scalar()


def test_connection_pragmas(app):
    assert _pragma('journal_mode') == 'wal'
    assert _pragma('foreign_keys') == 1
    assert _pragma('synchronous') == 1  # NORMAL
    assert _pragma('busy_timeout') == 5000


def test_every_app_table_is_strict(app):
    rows = sql.session.execute(text(
        "SELECT name, strict FROM pragma_table_list "
        "WHERE schema = 'main' AND name NOT LIKE 'sqlite_%' AND name != 'alembic_version'"
    )).all()
    assert {name for name, _ in rows} == set(sql.metadata.tables)
    assert all(strict for _, strict in rows)


def test_models_match_migrations(app):
    """Fails when a model changed without a migration: run
    `alembic revision --autogenerate -m "..."`."""
    diff = compare_metadata(MigrationContext.configure(sql.session.connection()), sql.metadata)
    assert diff == []


def test_strict_rejects_wrong_type(app, db):
    # A plain (non-STRICT) table would happily store the string.
    with pytest.raises(IntegrityError, match='cannot store TEXT value in INTEGER column'):
        sql.session.execute(text("UPDATE users SET is_admin = 'yes'"))
    sql.session.rollback()


def test_foreign_keys_are_enforced(app, db):
    with pytest.raises(IntegrityError):
        sql.session.execute(text(
            "INSERT INTO locations (association_id, room, spot) VALUES (999999, 'Nowhere', '')"))
    sql.session.rollback()


def _make_mini(db, **kwargs):
    defaults = dict(association=db['assoc'], category='Miniature', type='Infantry',
                    game=db['game'], scale='28mm', quantity=1, location=db['loc'])
    return save(Miniature(**{**defaults, **kwargs}))


def test_ids_are_not_reused(app, db):
    first_item = _make_mini(db)
    first_id = first_item.id
    sql.session.delete(first_item)
    sql.session.commit()
    assert _make_mini(db).id > first_id


def test_legacy_object_id_url_redirects(client, db):
    item = _make_mini(db)
    save(LegacyObjectId(object_id='65f0c0ffee0123456789abcd', item_type='miniature', item_id=item.id))
    r = client.get('/test/miniatures/65f0c0ffee0123456789abcd')
    assert r.status_code == 301
    assert r.headers['Location'].endswith(f'/test/miniatures/{item.id}')


def test_unknown_legacy_object_id_is_404(client, db):
    assert client.get('/test/miniatures/65f0c0ffee0123456789abcd').status_code == 404


def test_legacy_object_id_of_another_type_is_404(client, db):
    item = _make_mini(db)
    save(LegacyObjectId(object_id='65f0c0ffee0123456789abcd', item_type='miniature', item_id=item.id))
    assert client.get('/test/terrains/65f0c0ffee0123456789abcd').status_code == 404


def test_duplicate_link_accepts_legacy_url(client, db):
    a = _make_mini(db)
    b = _make_mini(db)
    save(LegacyObjectId(object_id='65f0c0ffee0123456789abcd', item_type='miniature', item_id=b.id))
    login(client, db['admin'])
    client.post(f'/test/miniatures/{a.id}/duplicates',
                data={'duplicate_url': 'http://localhost/test/miniatures/65f0c0ffee0123456789abcd'})
    from inventory.db.duplicate_link import DuplicateLink
    assert count(DuplicateLink, item1_id=a.id, item2_id=b.id) == 1


def test_item_of_another_association_is_404(client, db):
    other = save(Association(name='Other Asso', slug='other'))
    other_loc = save(Location(association=other, room='Elsewhere'))
    item = _make_mini(db, association=other, location=other_loc)
    login(client, db['admin'])
    assert client.get(f'/test/miniatures/{item.id}').status_code == 404
    assert client.get(f'/other/miniatures/{item.id}').status_code == 200
    for obj in (item, other_loc, other):
        sql.session.delete(obj)
        sql.session.commit()


def test_mongo_era_session_is_logged_out(client, db):
    with client.session_transaction() as sess:
        sess['user_id'] = '65f0c0ffee0123456789abcd'
    assert client.get('/test/miniatures/').status_code == 200
    with client.session_transaction() as sess:
        assert 'user_id' not in sess
