from flask import Blueprint, redirect, session, url_for

from inventory.api.oauth import oauth
from inventory.db.user import User

bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/discord')
def login():
    redirect_uri = url_for('auth.callback', _external=True)
    return oauth.discord.authorize_redirect(redirect_uri)


@bp.route('/discord/callback')
def callback():
    token = oauth.discord.authorize_access_token()
    info = oauth.discord.get('https://discord.com/api/users/@me', token=token).json()
    user = User.objects(discord_id=str(info['id'])).first()
    if not user:
        user = User(discord_id=str(info['id']), username=info['username'])
        user.save()
    elif user.username != info['username']:
        user.username = info['username']
        user.save()
    session['user_id'] = str(user.id)
    return redirect(url_for('index'))


@bp.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))
