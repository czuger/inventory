"""Alembic environment for the inventory's SQLite database.

The database URL comes from `sqlalchemy.url` when a caller sets it (the tests do),
and otherwise from `database_url()` — the same function the app uses, so
`alembic upgrade head` always migrates the database the app would open.

Importing the models also imports inventory/db/base.py, whose Engine-wide connect
hook sets the pragmas on Alembic's connections too, and whose type mapping makes
the CREATE TABLEs valid STRICT tables.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, event, pool

from inventory.db import models  # noqa: F401  (fills db.metadata)
from inventory.db.base import db
from inventory.libs.initialization import database_url

config = context.config

if config.config_file_name is not None:
    # Leave the app's loggers alone when migrations run inside it (tests, scripts).
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = db.metadata


def _url() -> str:
    return config.get_main_option('sqlalchemy.url') or database_url()


def run_migrations_offline() -> None:
    """Emit the SQL to stdout (`alembic upgrade head --sql`) instead of running it."""
    context.configure(
        url=_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={'paramstyle': 'named'},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)

    # By default sqlite3 only opens a transaction before INSERT/UPDATE/DELETE, so
    # DDL would commit statement by statement and a migration failing halfway
    # would leave a half-altered schema. SQLAlchemy's documented recipe: keep the
    # driver from issuing BEGIN at all and issue it ourselves, which makes each
    # `alembic upgrade` a single transaction. Only Alembic's engine does this;
    # the app keeps the driver's default.
    @event.listens_for(engine, 'connect')
    def _driver_autocommit(dbapi_connection, connection_record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, 'begin')
    def _begin(connection):
        connection.exec_driver_sql('BEGIN')

    with engine.connect() as connection:
        # Foreign keys off while migrating. SQLite cannot ALTER most of a table, so
        # batch mode rebuilds it (create copy, drop original, rename); with foreign
        # keys enforced, dropping a table other rows point at fails. This is the
        # procedure SQLite documents for schema changes, and it has to happen
        # here, outside the transaction: inside one the pragma is silently ignored.
        connection.connection.driver_connection.execute('PRAGMA foreign_keys=OFF')

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
            # Alembic assumes SQLite DDL cannot be transactional; with the two
            # hooks above it is, so let it wrap the whole run in one transaction.
            transactional_ddl=True,
        )
        with context.begin_transaction():
            context.run_migrations()
            # ...and the check foreign keys would have made, before committing.
            violations = connection.exec_driver_sql('PRAGMA foreign_key_check').fetchall()
            if violations:
                raise RuntimeError(f'migration left dangling foreign keys: {violations}')


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
