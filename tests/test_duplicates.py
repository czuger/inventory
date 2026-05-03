from inventory.db.board_game import BoardGame
from inventory.db.duplicate_link import DuplicateLink
from inventory.db.miniature import Miniature
from tests.conftest import login, logout


def _make_mini(db, **kwargs):
    return Miniature(
        association=db['assoc'], category='Miniature',
        type='Infantry', game=db['game'], scale='28mm',
        quantity=1, location=db['loc'], **kwargs,
    ).save()


def _make_board_game(db, **kwargs):
    return BoardGame(
        association=db['assoc'], category='Board Game',
        name='Catan', quantity=1, location=db['loc'], **kwargs,
    ).save()


def _mini_url(item):
    return f'http://localhost/test/miniatures/{item.id}'


def _board_game_url(item):
    return f'http://localhost/test/board-games/{item.id}'


def test_add_duplicate_link(client, db):
    a = _make_mini(db)
    b = _make_mini(db)
    login(client, db['admin'])
    r = client.post(f'/test/miniatures/{a.id}/duplicates',
                    data={'duplicate_url': _mini_url(b)},
                    follow_redirects=True)
    assert r.status_code == 200
    assert DuplicateLink.objects.count() == 1
    link = DuplicateLink.objects.first()
    assert link.item1_id == str(a.id)
    assert link.item2_id == str(b.id)


def test_add_duplicate_requires_admin(client, db):
    a = _make_mini(db)
    b = _make_mini(db)
    login(client, db['user'])
    r = client.post(f'/test/miniatures/{a.id}/duplicates',
                    data={'duplicate_url': _mini_url(b)})
    assert r.status_code == 403
    assert DuplicateLink.objects.count() == 0


def test_add_duplicate_rejects_self_link(client, db):
    a = _make_mini(db)
    login(client, db['admin'])
    client.post(f'/test/miniatures/{a.id}/duplicates',
                data={'duplicate_url': _mini_url(a)},
                follow_redirects=True)
    assert DuplicateLink.objects.count() == 0


def test_add_duplicate_rejects_double_link(client, db):
    a = _make_mini(db)
    b = _make_mini(db)
    login(client, db['admin'])
    client.post(f'/test/miniatures/{a.id}/duplicates',
                data={'duplicate_url': _mini_url(b)},
                follow_redirects=True)
    client.post(f'/test/miniatures/{a.id}/duplicates',
                data={'duplicate_url': _mini_url(b)},
                follow_redirects=True)
    assert DuplicateLink.objects.count() == 1


def test_add_duplicate_rejects_reverse_double_link(client, db):
    a = _make_mini(db)
    b = _make_mini(db)
    login(client, db['admin'])
    client.post(f'/test/miniatures/{a.id}/duplicates',
                data={'duplicate_url': _mini_url(b)},
                follow_redirects=True)
    client.post(f'/test/miniatures/{b.id}/duplicates',
                data={'duplicate_url': _mini_url(a)},
                follow_redirects=True)
    assert DuplicateLink.objects.count() == 1


def test_add_duplicate_invalid_url(client, db):
    a = _make_mini(db)
    login(client, db['admin'])
    client.post(f'/test/miniatures/{a.id}/duplicates',
                data={'duplicate_url': 'not-a-url'},
                follow_redirects=True)
    assert DuplicateLink.objects.count() == 0


def test_add_duplicate_nonexistent_item(client, db):
    a = _make_mini(db)
    login(client, db['admin'])
    fake_id = '000000000000000000000000'
    client.post(f'/test/miniatures/{a.id}/duplicates',
                data={'duplicate_url': f'http://localhost/test/miniatures/{fake_id}'},
                follow_redirects=True)
    assert DuplicateLink.objects.count() == 0


def test_delete_duplicate_link(client, db):
    a = _make_mini(db)
    b = _make_mini(db)
    login(client, db['admin'])
    client.post(f'/test/miniatures/{a.id}/duplicates',
                data={'duplicate_url': _mini_url(b)},
                follow_redirects=True)
    link = DuplicateLink.objects.first()
    r = client.post(f'/test/miniatures/{a.id}/duplicates/{link.id}/delete',
                    follow_redirects=True)
    assert r.status_code == 200
    assert DuplicateLink.objects.count() == 0


def test_delete_duplicate_requires_admin(client, db):
    a = _make_mini(db)
    b = _make_mini(db)
    link = DuplicateLink(
        association=db['assoc'], item1_id=str(a.id), item1_type='miniature',
        item2_id=str(b.id), item2_type='miniature',
    ).save()
    login(client, db['user'])
    r = client.post(f'/test/miniatures/{a.id}/duplicates/{link.id}/delete')
    assert r.status_code == 403
    assert DuplicateLink.objects.count() == 1


def test_duplicate_link_is_bidirectional(client, db):
    a = _make_mini(db)
    b = _make_mini(db)
    login(client, db['admin'])
    client.post(f'/test/miniatures/{a.id}/duplicates',
                data={'duplicate_url': _mini_url(b)},
                follow_redirects=True)
    # Link was created from a's side; b should see it too
    r = client.get(f'/test/miniatures/{b.id}', follow_redirects=True)
    assert r.status_code == 200
    # The link must be findable when querying from b's perspective
    link = DuplicateLink.objects.first()
    assert (link.item2_id == str(b.id) or link.item1_id == str(b.id))


def test_cross_type_duplicate(client, db):
    mini = _make_mini(db)
    bg = _make_board_game(db)
    login(client, db['admin'])
    r = client.post(f'/test/miniatures/{mini.id}/duplicates',
                    data={'duplicate_url': _board_game_url(bg)},
                    follow_redirects=True)
    assert r.status_code == 200
    assert DuplicateLink.objects.count() == 1
    link = DuplicateLink.objects.first()
    assert link.item1_type == 'miniature'
    assert link.item2_type == 'board_game'


def test_show_page_renders_duplicates_section(client, db):
    login(client, db['admin'])
    item = _make_mini(db)
    r = client.get(f'/test/miniatures/{item.id}')
    assert b'doublon' in r.data.lower()  # French: 'Doublons suspect\xe9s'


def test_edit_page_shows_duplicate_form_for_admin(client, db):
    login(client, db['admin'])
    item = _make_mini(db)
    r = client.get(f'/test/miniatures/{item.id}/edit')
    assert b'duplicate_url' in r.data


def test_edit_page_no_duplicate_form_for_non_admin(client, db):
    logout(client)
    login(client, db['user'])
    item = _make_mini(db)
    r = client.get(f'/test/miniatures/{item.id}/edit')
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        assert b'duplicate_url' not in r.data
