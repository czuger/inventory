"""`python -m inventory.db.migrate`: back up the database, then `alembic upgrade head`.

This is what a deploy runs (deploy/remote.sh), in a throwaway container of the new
image, before that image is started. When there is nothing to migrate it does
nothing at all; otherwise it first copies the database to data/backups/, because
an upgrade cannot always be undone by a rollback (which never downgrades).
"""
import os
import sqlite3
import sys

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from inventory.db.base import utcnow
from inventory.libs.initialization import database_url, find_project_root


def main() -> None:
    url = database_url()
    config = Config(os.path.join(find_project_root(), 'alembic.ini'))
    config.set_main_option('sqlalchemy.url', url.replace('%', '%%'))

    head = ScriptDirectory.from_config(config).get_current_head()
    engine = create_engine(url)
    with engine.connect() as connection:
        current = MigrationContext.configure(connection).get_current_revision()
    engine.dispose()

    if current == head:
        print(f'database at {head}, nothing to migrate')
        return

    path = make_url(url).database
    if current is not None and path and os.path.exists(path):
        backup_dir = os.path.join(os.path.dirname(path), 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup = os.path.join(backup_dir, f'{utcnow():%Y%m%d-%H%M%S}-before-{head}.sqlite3')
        # The online backup API, not a file copy: it is consistent even while the
        # running app writes, and it folds in what is still in the -wal file.
        with sqlite3.connect(path) as src, sqlite3.connect(backup) as dst:
            src.backup(dst)
        print(f'backed up to {backup}')

    print(f'migrating {current or "an empty database"} -> {head}')
    command.upgrade(config, 'head')


if __name__ == '__main__':
    sys.exit(main())
