from unittest.mock import MagicMock, patch

from flask import redirect as flask_redirect

from inventory.db.user import User
from tests.conftest import count, first, login, reload, remove, save


def test_logout_clears_session(client, db):
    login(client, db['admin'])
    with client.session_transaction() as sess:
        assert 'user_id' in sess
    client.get('/auth/logout', follow_redirects=False)
    with client.session_transaction() as sess:
        assert 'user_id' not in sess


def test_logout_unauthenticated_is_harmless(client, db):
    r = client.get('/auth/logout', follow_redirects=False)
    assert r.status_code == 302


def test_login_redirects_to_discord(client, db):
    with patch('inventory.api.routes.auth.oauth') as mock_oauth:
        mock_oauth.discord.authorize_redirect.return_value = flask_redirect(
            'https://discord.com/oauth2/authorize'
        )
        r = client.get('/auth/discord', follow_redirects=False)
    assert r.status_code == 302
    mock_oauth.discord.authorize_redirect.assert_called_once()


def test_callback_creates_new_user(client, db):
    with patch('inventory.api.routes.auth.oauth') as mock_oauth:
        mock_oauth.discord.authorize_access_token.return_value = {'access_token': 'tok'}
        resp = MagicMock()
        resp.json.return_value = {'id': '999', 'username': 'newplayer', 'global_name': 'New Player'}
        mock_oauth.discord.get.return_value = resp
        r = client.get('/auth/discord/callback', follow_redirects=False)
    assert r.status_code == 302
    user = first(User, discord_id='999')
    assert user is not None
    assert user.username == 'newplayer'
    assert user.display_name == 'New Player'
    with client.session_transaction() as sess:
        assert sess.get('user_id') == user.id
    remove(user)


def test_callback_updates_existing_user(client, db):
    existing = save(User(discord_id='888', username='old_name', is_admin=False))
    with patch('inventory.api.routes.auth.oauth') as mock_oauth:
        mock_oauth.discord.authorize_access_token.return_value = {'access_token': 'tok'}
        resp = MagicMock()
        resp.json.return_value = {'id': '888', 'username': 'new_name', 'global_name': None}
        mock_oauth.discord.get.return_value = resp
        client.get('/auth/discord/callback', follow_redirects=False)
    reload(existing)
    assert existing.username == 'new_name'
    assert existing.display_name is None
    remove(existing)


def test_callback_no_update_if_unchanged(client, db):
    existing = save(User(discord_id='777', username='stable', display_name='Stable'))
    with patch('inventory.api.routes.auth.oauth') as mock_oauth:
        mock_oauth.discord.authorize_access_token.return_value = {'access_token': 'tok'}
        resp = MagicMock()
        resp.json.return_value = {'id': '777', 'username': 'stable', 'global_name': 'Stable'}
        mock_oauth.discord.get.return_value = resp
        client.get('/auth/discord/callback', follow_redirects=False)
    assert count(User, discord_id='777') == 1
    remove(existing)


def test_language_switch_to_en(client, db):
    r = client.get('/set-language/en', follow_redirects=False)
    assert r.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get('lang') == 'en'


def test_language_switch_to_fr(client, db):
    r = client.get('/set-language/fr', follow_redirects=False)
    assert r.status_code == 302
    with client.session_transaction() as sess:
        assert sess.get('lang') == 'fr'


def test_language_invalid_ignored(client, db):
    with client.session_transaction() as sess:
        sess['lang'] = 'fr'
    client.get('/set-language/de', follow_redirects=False)
    with client.session_transaction() as sess:
        assert sess.get('lang') == 'fr'
