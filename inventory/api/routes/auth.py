import logging

from flask import Blueprint, redirect, session, url_for
from sqlalchemy import select

from inventory.api.oauth import oauth
from inventory.db.base import db
from inventory.db.user import User

logger = logging.getLogger(__name__)

bp = Blueprint('auth', __name__, url_prefix='/auth')


@bp.route('/discord')
def login():
    redirect_uri = url_for('auth.callback', _external=True)
    logger.info("OAuth callback URL: %s", redirect_uri)
    return oauth.discord.authorize_redirect(redirect_uri)


@bp.route('/discord/callback')
def callback():
    token = oauth.discord.authorize_access_token()
    info = oauth.discord.get('https://discord.com/api/users/@me', token=token).json()
    user = db.session.scalar(select(User).filter_by(discord_id=str(info['id'])))
    new_username     = info['username']
    new_display_name = info.get('global_name') or None
    if not user:
        user = User(discord_id=str(info['id']), username=new_username, display_name=new_display_name)
        db.session.add(user)
        db.session.commit()
    elif user.username != new_username or user.display_name != new_display_name:
        user.username     = new_username
        user.display_name = new_display_name
        db.session.commit()
    session['user_id'] = user.id
    return redirect(url_for('index'))


@bp.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))
