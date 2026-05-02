import pytest

from inventory.db.board_game import BoardGame
from inventory.db.book import Book
from inventory.db.borrowing import Borrowing
from inventory.db.consumable import Consumable
from inventory.db.equipment import Equipment
from inventory.db.miniature import Miniature
from inventory.db.rulebook import Rulebook
from inventory.db.tablecloth import Tablecloth
from inventory.db.terrain import Terrain
from tests.conftest import login, logout

ITEM_CONFIGS = [
    dict(
        item_type='miniature',
        Model=Miniature,
        prefix='miniatures',
        make=lambda db: Miniature(
            association=db['assoc'], category='Miniature',
            type='Infantry', game=db['game'], scale='28mm',
            quantity=2, location=db['loc'],
        ).save(),
        form=lambda db: dict(
            category='Miniature', type='Infantry',
            game=str(db['game'].id), scale='28mm',
            quantity='2', location=str(db['loc'].id),
        ),
        edit_field=('type', 'Cavalry'),
    ),
    dict(
        item_type='terrain',
        Model=Terrain,
        prefix='terrains',
        make=lambda db: Terrain(
            association=db['assoc'], category='Terrain',
            type='Forest', game=db['game'], scale='28mm',
            quantity=1, location=db['loc'],
        ).save(),
        form=lambda db: dict(
            category='Terrain', type='Forest',
            game=str(db['game'].id), scale='28mm',
            quantity='1', location=str(db['loc'].id),
        ),
        edit_field=('type', 'Hills'),
    ),
    dict(
        item_type='tablecloth',
        Model=Tablecloth,
        prefix='tablecloths',
        make=lambda db: Tablecloth(
            association=db['assoc'], category='Tablecloth',
            type='Green Field', game=db['game'], size='120x180',
            quantity=1, location=db['loc'],
        ).save(),
        form=lambda db: dict(
            category='Tablecloth', type='Green Field',
            game=str(db['game'].id), size='120x180',
            quantity='1', location=str(db['loc'].id),
        ),
        edit_field=('type', 'Blue Sea'),
    ),
    dict(
        item_type='rulebook',
        Model=Rulebook,
        prefix='rulebooks',
        make=lambda db: Rulebook(
            association=db['assoc'], category='Rulebook',
            name='Core Rules', game=db['game'], supplement=False,
            quantity=1, location=db['loc'],
        ).save(),
        form=lambda db: dict(
            category='Rulebook', name='Core Rules',
            game=str(db['game'].id), quantity='1',
            location=str(db['loc'].id),
        ),
        edit_field=('name', 'Advanced Rules'),
    ),
    dict(
        item_type='board_game',
        Model=BoardGame,
        prefix='board-games',
        make=lambda db: BoardGame(
            association=db['assoc'], category='Board Game',
            name='Chess', quantity=1, location=db['loc'],
        ).save(),
        form=lambda db: dict(
            category='Board Game', name='Chess',
            quantity='1', location=str(db['loc'].id),
        ),
        edit_field=('name', 'Checkers'),
    ),
    dict(
        item_type='book',
        Model=Book,
        prefix='books',
        make=lambda db: Book(
            association=db['assoc'], category='Book',
            name='War History', quantity=1, location=db['loc'],
        ).save(),
        form=lambda db: dict(
            category='Book', name='War History',
            quantity='1', location=str(db['loc'].id),
        ),
        edit_field=('name', 'Peace History'),
    ),
    dict(
        item_type='equipment',
        Model=Equipment,
        prefix='equipment',
        make=lambda db: Equipment(
            association=db['assoc'], category='Equipment',
            type='Brush', quantity=1, location=db['loc'],
        ).save(),
        form=lambda db: dict(
            category='Equipment', type='Brush',
            quantity='1', location=str(db['loc'].id),
        ),
        edit_field=('type', 'Dice Bag'),
    ),
    dict(
        item_type='consumable',
        Model=Consumable,
        prefix='consumables',
        make=lambda db: Consumable(
            association=db['assoc'], category='Consumable',
            type='Paint', quantity=3, location=db['loc'],
        ).save(),
        form=lambda db: dict(
            category='Consumable', type='Paint',
            quantity='3', location=str(db['loc'].id),
        ),
        edit_field=('type', 'Varnish'),
    ),
]

IDS = [c['item_type'] for c in ITEM_CONFIGS]


@pytest.mark.parametrize('cfg', ITEM_CONFIGS, ids=IDS)
class TestItemCRUD:

    def test_index(self, client, db, cfg):
        login(client, db['admin'])
        r = client.get(f'/test/{cfg["prefix"]}/')
        assert r.status_code == 200

    def test_create(self, client, db, cfg):
        login(client, db['admin'])
        r = client.post(f'/test/{cfg["prefix"]}/new',
                        data=cfg['form'](db), follow_redirects=True)
        assert r.status_code == 200
        assert cfg['Model'].objects(association=db['assoc']).count() == 1

    def test_show(self, client, db, cfg):
        item = cfg['make'](db)
        login(client, db['admin'])
        r = client.get(f'/test/{cfg["prefix"]}/{item.id}')
        assert r.status_code == 200

    def test_edit(self, client, db, cfg):
        item = cfg['make'](db)
        login(client, db['admin'])
        form = dict(cfg['form'](db))
        field, new_val = cfg['edit_field']
        form[field] = new_val
        r = client.post(f'/test/{cfg["prefix"]}/{item.id}/edit',
                        data=form, follow_redirects=True)
        assert r.status_code == 200
        item.reload()
        assert getattr(item, field) == new_val

    def test_delete(self, client, db, cfg):
        item = cfg['make'](db)
        login(client, db['admin'])
        client.post(f'/test/{cfg["prefix"]}/{item.id}/delete')
        assert cfg['Model'].objects(id=item.id).count() == 0

    def test_create_requires_admin(self, client, db, cfg):
        login(client, db['user'])
        r = client.post(f'/test/{cfg["prefix"]}/new', data=cfg['form'](db))
        assert r.status_code == 403

    def test_edit_requires_admin(self, client, db, cfg):
        item = cfg['make'](db)
        login(client, db['user'])
        r = client.post(f'/test/{cfg["prefix"]}/{item.id}/edit',
                        data=cfg['form'](db))
        assert r.status_code == 403

    def test_delete_requires_admin(self, client, db, cfg):
        item = cfg['make'](db)
        login(client, db['user'])
        r = client.post(f'/test/{cfg["prefix"]}/{item.id}/delete')
        assert r.status_code == 403

    def test_borrow(self, client, db, cfg):
        item = cfg['make'](db)
        login(client, db['user'])
        client.post(f'/test/{cfg["prefix"]}/{item.id}/borrow',
                    follow_redirects=True)
        item.reload()
        assert item.borrowing_count == 1
        assert Borrowing.objects(item_id=str(item.id), action='borrow').count() == 1

    def test_return(self, client, db, cfg):
        item = cfg['make'](db)
        item.borrowing_count = 1
        item.save()
        login(client, db['user'])
        client.post(f'/test/{cfg["prefix"]}/{item.id}/return',
                    follow_redirects=True)
        item.reload()
        assert item.borrowing_count == 0
        assert Borrowing.objects(item_id=str(item.id), action='return').count() == 1

    def test_borrow_requires_auth(self, client, db, cfg):
        item = cfg['make'](db)
        r = client.post(f'/test/{cfg["prefix"]}/{item.id}/borrow')
        assert r.status_code == 401

    def test_stickers_marks_printed(self, client, db, cfg):
        item = cfg['make'](db)
        assert not item.sticker_printed
        login(client, db['admin'])
        r = client.get(f'/test/{cfg["prefix"]}/stickers')
        assert r.status_code == 200
        assert r.content_type == 'application/pdf'
        item.reload()
        assert item.sticker_printed

    def test_edit_resets_sticker(self, client, db, cfg):
        item = cfg['make'](db)
        item.sticker_printed = True
        item.save()
        login(client, db['admin'])
        client.post(f'/test/{cfg["prefix"]}/{item.id}/edit',
                    data=cfg['form'](db), follow_redirects=True)
        item.reload()
        assert not item.sticker_printed

    def test_edit_keeps_sticker_when_checked(self, client, db, cfg):
        item = cfg['make'](db)
        item.sticker_printed = True
        item.save()
        login(client, db['admin'])
        form = dict(cfg['form'](db))
        form['sticker_printed'] = 'on'
        client.post(f'/test/{cfg["prefix"]}/{item.id}/edit',
                    data=form, follow_redirects=True)
        item.reload()
        assert item.sticker_printed
