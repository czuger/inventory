"""The SQLAlchemy foundation every model builds on.

Everything SQLite-specific that must hold on *every* connection and in *every*
CREATE TABLE lives here, so that the app, Alembic and the one-off scripts all get
it just by importing a model:

- `STRICT` tables, and the column type names they accept;
- the per-connection pragmas (WAL, synchronous, foreign keys, busy timeout).
"""
import sqlite3
from datetime import UTC, datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import JSON, Boolean, DateTime, Engine, MetaData, String, event
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import DeclarativeBase

# Every table is created with these options (`__table_args__ = STRICT` or as the last
# element of a tuple):
#
# - sqlite_strict: SQLite rejects a value of the wrong type instead of storing it
#   anyway, which is what it does by default ("type affinity"). Needs SQLite 3.37+.
# - sqlite_autoincrement: ids are never reused. Without it SQLite hands the id of the
#   most recently deleted row to the next insert, and here that would be harmful:
#   Borrowing and DuplicateLink point at items through a plain (item_type, item_id)
#   pair that no foreign key can guard, and uploaded photos live under
#   uploads/<category>/<item_id>/ — a new item would inherit the borrowing history,
#   duplicate links and photo folder of a deleted one.
STRICT = {'sqlite_strict': True, 'sqlite_autoincrement': True}


# STRICT tables only accept the column types INT, INTEGER, REAL, TEXT, BLOB and ANY;
# SQLAlchemy's default names for these types (VARCHAR, BOOLEAN, DATETIME, JSON) would
# make every CREATE TABLE fail. The Python side is unchanged: SQLAlchemy still
# converts bool <-> 0/1, datetime <-> ISO string and list <-> JSON text.
@compiles(String, 'sqlite')
@compiles(DateTime, 'sqlite')
@compiles(JSON, 'sqlite')
def _compile_as_text(type_, compiler, **kw):
    return 'TEXT'


@compiles(Boolean, 'sqlite')
def _compile_as_integer(type_, compiler, **kw):
    return 'INTEGER'


@event.listens_for(Engine, 'connect')
def _set_sqlite_pragmas(dbapi_connection, connection_record):
    """Applied to every new connection of every engine, Alembic's included.

    - journal_mode=WAL: readers no longer block the writer and vice versa, which
      matters with two gunicorn workers. It is stored in the database file, so
      repeating it per connection is a cheap no-op.
    - synchronous=NORMAL: the recommended setting with WAL. A commit survives an
      application crash; only a power loss can drop the last few commits, and it
      can never corrupt the database. FULL would fsync on every commit for nothing
      this app needs.
    - foreign_keys=ON: SQLite ships with foreign keys *off*, per connection, so
      without this every ForeignKey below would be decoration.
    - busy_timeout: a write that finds the database locked by the other worker
      waits up to 5s instead of failing at once with "database is locked".
    """
    if not isinstance(dbapi_connection, sqlite3.Connection):
        return
    cursor = dbapi_connection.cursor()
    cursor.execute('PRAGMA journal_mode=WAL')
    cursor.execute('PRAGMA synchronous=NORMAL')
    cursor.execute('PRAGMA foreign_keys=ON')
    cursor.execute('PRAGMA busy_timeout=5000')
    cursor.close()


class Base(DeclarativeBase):
    # Deterministic constraint names. Alembic's batch mode (the only way to alter a
    # SQLite table) recreates tables and needs names to find constraints again.
    metadata = MetaData(naming_convention={
        'ix': 'ix_%(column_0_label)s',
        'uq': 'uq_%(table_name)s_%(column_0_N_name)s',
        'ck': 'ck_%(table_name)s_%(constraint_name)s',
        'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
        'pk': 'pk_%(table_name)s',
    })


db = SQLAlchemy(model_class=Base)


def utcnow() -> datetime:
    """Naive UTC, like the datetimes MongoDB used to return, so migrated and new
    rows compare and sort the same way."""
    return datetime.now(UTC).replace(tzinfo=None)
