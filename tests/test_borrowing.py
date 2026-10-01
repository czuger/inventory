from sqlalchemy import select

from inventory.db.base import db as sql
from inventory.db.borrowing import Borrowing
from inventory.db.miniature import Miniature
from tests.conftest import first, login, reload, save


def _make_mini(db, **kwargs):
    return save(Miniature(
        association=db['assoc'], category='Miniature',
        type='Infantry', game=db['game'], scale='28mm',
        quantity=3, location=db['loc'], **kwargs,
    ))


def test_borrow_increments_count(client, db):
    item = _make_mini(db)
    login(client, db['user'])
    client.post(f'/test/miniatures/{item.id}/borrow', follow_redirects=True)
    client.post(f'/test/miniatures/{item.id}/borrow', follow_redirects=True)
    reload(item)
    assert item.borrowing_count == 2


def test_return_decrements_count(client, db):
    item = _make_mini(db, borrowing_count=2)
    login(client, db['user'])
    client.post(f'/test/miniatures/{item.id}/return', follow_redirects=True)
    reload(item)
    assert item.borrowing_count == 1


def test_return_floor_at_zero(client, db):
    item = _make_mini(db, borrowing_count=0)
    login(client, db['user'])
    client.post(f'/test/miniatures/{item.id}/return', follow_redirects=True)
    reload(item)
    assert item.borrowing_count == 0


def test_borrowing_records_user(client, db):
    item = _make_mini(db)
    login(client, db['user'])
    client.post(f'/test/miniatures/{item.id}/borrow', follow_redirects=True)
    record = first(Borrowing, item_id=item.id)
    assert record is not None
    assert record.borrower.id == db['user'].id
    assert record.action == 'borrow'


def test_borrow_history_order(client, db):
    item = _make_mini(db)
    login(client, db['user'])
    client.post(f'/test/miniatures/{item.id}/borrow', follow_redirects=True)
    client.post(f'/test/miniatures/{item.id}/return', follow_redirects=True)
    records = sql.session.scalars(
        select(Borrowing).filter_by(item_id=item.id).order_by(Borrowing.date.desc(), Borrowing.id.desc())
    ).all()
    assert len(records) == 2
    assert records[0].action == 'return'
    assert records[1].action == 'borrow'


def test_borrow_creates_association_record(client, db):
    item = _make_mini(db)
    login(client, db['user'])
    client.post(f'/test/miniatures/{item.id}/borrow', follow_redirects=True)
    record = first(Borrowing, item_id=item.id)
    assert record.association.id == db['assoc'].id
