"""
Grant or revoke admin rights for a Discord user.

Usage:
    python misc/set_admin.py <discord_username>           # grant admin
    python misc/set_admin.py <discord_username> --revoke  # revoke admin
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from flask import Flask
from sqlalchemy import select

from inventory.db.base import db
from inventory.db.user import User
from inventory.libs.initialization import initialize


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    username = sys.argv[1]
    revoke = '--revoke' in sys.argv

    app = Flask(__name__)
    initialize(app)

    with app.app_context():
        user = db.session.scalar(select(User).filter_by(username=username))
        if not user:
            print(f"No user found with username '{username}'.")
            print("Users must log in via Discord at least once before being granted admin.")
            sys.exit(1)

        user.is_admin = not revoke
        db.session.commit()
        action = 'revoked' if revoke else 'granted'
        print(f"Admin {action} for '{username}' (discord_id: {user.discord_id}).")


if __name__ == '__main__':
    main()
