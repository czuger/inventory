from inventory.db.board_game import BoardGame
from inventory.db.book import Book
from inventory.db.consumable import Consumable
from inventory.db.equipment import Equipment
from inventory.db.miniature import Miniature
from inventory.db.rulebook import Rulebook
from inventory.db.tablecloth import Tablecloth
from inventory.db.terrain import Terrain
from tests.conftest import login


def _make_one_of_each(db):
    mini = Miniature(association=db['assoc'], category='Miniature',
                     type='Infantry', game=db['game'], scale='28mm',
                     quantity=1, location=db['loc']).save()
    terrain = Terrain(association=db['assoc'], category='Terrain',
                      type='Forest', game=db['game'], scale='28mm',
                      quantity=1, location=db['loc']).save()
    cloth = Tablecloth(association=db['assoc'], category='Tablecloth',
                       type='Green', game=db['game'], size='120x180',
                       quantity=1, location=db['loc']).save()
    rule = Rulebook(association=db['assoc'], category='Rulebook',
                    name='Rules', game=db['game'], quantity=1,
                    location=db['loc']).save()
    bg = BoardGame(association=db['assoc'], category='Board Game',
                   name='Chess', quantity=1, location=db['loc']).save()
    book = Book(association=db['assoc'], category='Book',
                name='History', quantity=1, location=db['loc']).save()
    equip = Equipment(association=db['assoc'], category='Equipment',
                      type='Brush', quantity=1, location=db['loc']).save()
    cons = Consumable(association=db['assoc'], category='Consumable',
                      type='Paint', quantity=2, location=db['loc']).save()
    return dict(mini=mini, terrain=terrain, cloth=cloth, rule=rule,
                bg=bg, book=book, equip=equip, cons=cons)


def test_index(client, db):
    login(client, db['admin'])
    r = client.get('/test/print/')
    assert r.status_code == 200
    assert b'Miniature' in r.data or b'miniature' in r.data.lower()


def test_index_requires_admin(client, db):
    login(client, db['user'])
    r = client.get('/test/print/')
    assert r.status_code == 403


def test_index_unauthenticated(client, db):
    r = client.get('/test/print/')
    assert r.status_code == 403


def test_stickers_full_returns_pdf(client, db):
    _make_one_of_each(db)
    login(client, db['admin'])
    r = client.post('/test/print/stickers', data={'mode': 'full'})
    assert r.status_code == 200
    assert r.content_type == 'application/pdf'
    assert len(r.data) > 0


def test_stickers_full_marks_all_printed(client, db):
    items = _make_one_of_each(db)
    login(client, db['admin'])
    client.post('/test/print/stickers', data={'mode': 'full'})
    for item in items.values():
        item.reload()
        assert item.sticker_printed


def test_stickers_new_only_skips_printed(client, db):
    items = _make_one_of_each(db)
    items['mini'].sticker_printed = True
    items['mini'].save()
    login(client, db['admin'])
    client.post('/test/print/stickers', data={'mode': 'new'})
    items['mini'].reload()
    assert items['mini'].sticker_printed  # was already True, unchanged
    items['terrain'].reload()
    assert items['terrain'].sticker_printed  # was False, now True


def test_stickers_new_only_marks_unprinted(client, db):
    items = _make_one_of_each(db)
    login(client, db['admin'])
    # first pass: print all
    client.post('/test/print/stickers', data={'mode': 'full'})
    # reset one item
    items['mini'].sticker_printed = False
    items['mini'].save()
    # second pass: new only
    client.post('/test/print/stickers', data={'mode': 'new'})
    items['mini'].reload()
    assert items['mini'].sticker_printed


def test_stickers_category_filters(client, db):
    items = _make_one_of_each(db)
    login(client, db['admin'])
    r = client.post('/test/print/stickers',
                    data={'mode': 'category', 'category': 'Miniature'})
    assert r.status_code == 200
    assert r.content_type == 'application/pdf'
    items['mini'].reload()
    items['terrain'].reload()
    assert items['mini'].sticker_printed
    assert not items['terrain'].sticker_printed


def test_print_list_full_returns_pdf(client, db):
    _make_one_of_each(db)
    login(client, db['admin'])
    r = client.post('/test/print/list', data={'mode': 'full'})
    assert r.status_code == 200
    assert r.content_type == 'application/pdf'
    assert len(r.data) > 0


def test_print_list_new_only(client, db):
    items = _make_one_of_each(db)
    items['mini'].sticker_printed = True
    items['mini'].save()
    login(client, db['admin'])
    r = client.post('/test/print/list', data={'mode': 'new'})
    assert r.status_code == 200
    assert r.content_type == 'application/pdf'


def test_print_list_category(client, db):
    _make_one_of_each(db)
    login(client, db['admin'])
    r = client.post('/test/print/list',
                    data={'mode': 'category', 'category': 'Terrain'})
    assert r.status_code == 200
    assert r.content_type == 'application/pdf'


def test_stickers_requires_admin(client, db):
    login(client, db['user'])
    r = client.post('/test/print/stickers', data={'mode': 'full'})
    assert r.status_code == 403


def test_print_list_requires_admin(client, db):
    login(client, db['user'])
    r = client.post('/test/print/list', data={'mode': 'full'})
    assert r.status_code == 403
