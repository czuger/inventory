from inventory.db.borrowing import Borrowing
from inventory.db.miniature import Miniature
from tests.conftest import login


def _make_mini(db, **kwargs):
    return Miniature(
        association=db['assoc'], category='Miniature',
        type='Infantry', game=db['game'], scale='28mm',
        quantity=3, location=db['loc'], **kwargs,
    ).save()


def test_borrow_increments_count(client, db):
    item = _make_mini(db)
    login(client, db['user'])
    client.post(f'/test/miniatures/{item.id}/borrow', follow_redirects=True)
    client.post(f'/test/miniatures/{item.id}/borrow', follow_redirects=True)
    item.reload()
    assert item.borrowing_count == 2


def test_return_decrements_count(client, db):
    item = _make_mini(db, borrowing_count=2)
    login(client, db['user'])
    client.post(f'/test/miniatures/{item.id}/return', follow_redirects=True)
    item.reload()
    assert item.borrowing_count == 1


def test_return_floor_at_zero(client, db):
    item = _make_mini(db, borrowing_count=0)
    login(client, db['user'])
    client.post(f'/test/miniatures/{item.id}/return', follow_redirects=True)
    item.reload()
    assert item.borrowing_count == 0


def test_borrowing_records_user(client, db):
    item = _make_mini(db)
    login(client, db['user'])
    client.post(f'/test/miniatures/{item.id}/borrow', follow_redirects=True)
    record = Borrowing.objects(item_id=str(item.id)).first()
    assert record is not None
    assert str(record.borrower.id) == str(db['user'].id)
    assert record.action == 'borrow'


def test_borrow_history_order(client, db):
    item = _make_mini(db)
    login(client, db['user'])
    client.post(f'/test/miniatures/{item.id}/borrow', follow_redirects=True)
    client.post(f'/test/miniatures/{item.id}/return', follow_redirects=True)
    records = list(Borrowing.objects(item_id=str(item.id)).order_by('-date'))
    assert len(records) == 2
    assert records[0].action == 'return'
    assert records[1].action == 'borrow'


def test_borrow_creates_association_record(client, db):
    item = _make_mini(db)
    login(client, db['user'])
    client.post(f'/test/miniatures/{item.id}/borrow', follow_redirects=True)
    record = Borrowing.objects(item_id=str(item.id)).first()
    assert str(record.association.id) == str(db['assoc'].id)
