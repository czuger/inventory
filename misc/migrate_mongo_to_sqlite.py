"""
One-time import of the MongoDB data into the SQLite database.

Usage:
    pip install 'pymongo~=4.16'        # no longer an app dependency
    python misc/migrate_mongo_to_sqlite.py [--sqlite PATH] [--mongo-db NAME]
                                           [--uploads-dir DIR] [--skip-orphans] [--dry-run]

Reads MongoDB with the credentials of config.json's "mongo" section, exactly as
the app used to connect. Writes to --sqlite, or else to the database the app
would open (DATABASE_URL, else data/inventory.sqlite3). The target is brought to
the latest Alembic revision first and must be empty: the import never merges.

Every document gets a new integer id, numbered in ObjectId (= creation) order,
and references are remapped through an ObjectId -> id table kept per
collection. Each item's ObjectId is also stored in `legacy_object_ids`, which is
what keeps the QR codes of stickers printed before the move working.

Photos live in uploads/<category>/<ObjectId>/; with --uploads-dir those folders
are renamed to uploads/<category>/<new id>/ once the import has committed.

Nothing is written when a problem is found (a reference to a missing document,
a missing required field...): the script lists them all and exits with status 1.
--skip-orphans leaves out, and reports, items whose association no longer exists
instead: the app filters every list by association, so nobody could see them.
--dry-run goes through the whole import and then rolls it back.
"""
import argparse
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from bson import DBRef, ObjectId  # noqa: E402
from flask import Flask  # noqa: E402
from pymongo import MongoClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from inventory.db.base import db  # noqa: E402
from inventory.db.models import (  # noqa: E402
    Association, BoardGame, Book, Borrowing, Consumable, DuplicateLink, Equipment, Game, LegacyObjectId, Location,
    Miniature, Rulebook, Tablecloth, Terrain, User,
)
from inventory.libs.initialization import database_url, find_project_root, load_config  # noqa: E402

# Fields every item collection shares (besides _id), and the item-specific ones.
ITEM_COMMON = ['association', 'category', 'quantity', 'borrowing_count', 'sticker_printed', 'location', 'images']

# (item_type, Mongo collection, model, own scalar fields, has a `game` reference)
ITEM_TYPES = [
    ('miniature',  'miniatures',  Miniature,  ['type', 'scale'], True),
    ('terrain',    'terrains',    Terrain,    ['type', 'scale', 'theater'], True),
    # Sic: the MongoEngine model really did store tablecloths in "tablecoths".
    ('tablecloth', 'tablecoths',  Tablecloth, ['type', 'material', 'size', 'remarks'], True),
    ('rulebook',   'rulebooks',   Rulebook,   ['name', 'supplement'], True),
    ('board_game', 'board_games', BoardGame,  ['name', 'universe'], False),
    ('book',       'books',       Book,       ['name', 'universe', 'period'], False),
    ('equipment',  'equipment',   Equipment,  ['type'], False),
    ('consumable', 'consumables', Consumable, ['type', 'unit'], False),
]

# Collections no current code reads: the early `inventaire`/`categories` models, and
# `scales`/`tablecloth_sizes`, replaced by inventory/db/constants.py in 7575708.
KNOWN_UNUSED = {'inventaire', 'categories', 'scales', 'tablecloth_sizes'}


class Importer:
    def __init__(self, mongo, skip_orphans=False):
        self.mongo = mongo
        self.skip_orphans = skip_orphans
        self.ids = defaultdict(dict)      # collection -> {ObjectId: new int id}
        self.problems = []                # fatal: nothing is committed
        self.skipped = Counter()          # dropped on purpose, reported
        self.unknown_fields = defaultdict(set)
        self.counts = Counter()

    # --- helpers ------------------------------------------------------------

    def docs(self, collection, fields):
        """Documents in ObjectId order; notes fields the new schema has no place for."""
        expected = set(fields) | {'_id', '_cls'}
        for doc in self.mongo[collection].find().sort('_id', 1):
            self.unknown_fields[collection] |= set(doc) - expected
            yield doc

    def problem(self, collection, doc, message):
        self.problems.append(f"{collection} {doc.get('_id')}: {message}")

    def lookup(self, doc, field, target):
        """New id of the document `doc[field]` points to in `target`, or None."""
        value = doc.get(field)
        if isinstance(value, DBRef):
            value = value.id
        if value is None:
            return None
        return self.ids[target].get(ObjectId(value) if isinstance(value, str) else value)

    def ref(self, collection, doc, field, target):
        """Like lookup(), but a missing or dangling reference is a problem."""
        new_id = self.lookup(doc, field, target)
        if new_id is None:
            value = doc.get(field)
            self.problem(collection, doc, f"missing required reference '{field}'" if value is None
                         else f"'{field}' points to {value}, which is not in '{target}'")
        return new_id

    def required(self, collection, doc, *fields):
        missing = [f for f in fields if doc.get(f) in (None, '')]
        for f in missing:
            self.problem(collection, doc, f"missing required field '{f}'")
        return not missing

    def insert(self, collection, doc, row):
        db.session.add(row)
        db.session.flush()
        self.ids[collection][doc['_id']] = row.id
        self.counts[row.__tablename__] += 1
        return row

    @staticmethod
    def present(doc, *fields):
        """The given fields that are set; absent ones fall back to the model defaults."""
        return {f: doc[f] for f in fields if doc.get(f) is not None}

    # --- collections ----------------------------------------------------------

    def run(self):
        for doc in self.docs('associations', ['name', 'slug']):
            if self.required('associations', doc, 'name', 'slug'):
                self.insert('associations', doc, Association(name=doc['name'], slug=doc['slug']))

        for doc in self.docs('games', ['name']):
            if self.required('games', doc, 'name'):
                self.insert('games', doc, Game(name=doc['name']))

        for doc in self.docs('users', ['discord_id', 'username', 'display_name', 'is_admin']):
            if self.required('users', doc, 'discord_id', 'username'):
                self.insert('users', doc, User(
                    discord_id=str(doc['discord_id']),
                    **self.present(doc, 'username', 'display_name', 'is_admin'),
                ))

        for doc in self.docs('locations', ['association', 'room', 'spot']):
            assoc_id = self.ref('locations', doc, 'association', 'associations')
            if self.required('locations', doc, 'room') and assoc_id:
                # '' rather than NULL: see the unique constraint on Location.
                self.insert('locations', doc, Location(
                    association_id=assoc_id, room=doc['room'], spot=doc.get('spot') or ''))

        for item_type, collection, Model, own, has_game in ITEM_TYPES:
            self.import_items(item_type, collection, Model, own, has_game)

        self.import_borrowings()
        self.import_duplicate_links()

    def import_items(self, item_type, collection, Model, own, has_game):
        fields = ITEM_COMMON + own + (['game'] if has_game else [])
        required = ['category'] + [c.name for c in Model.__table__.columns
                                   if c.name in own and not c.nullable and c.default is None]
        for doc in self.docs(collection, fields):
            if self.skip_orphans and self.lookup(doc, 'association', 'associations') is None:
                self.skipped[f'{collection} of a deleted association: {doc["_id"]}'] += 1
                continue
            refs = dict(
                association_id=self.ref(collection, doc, 'association', 'associations'),
                location_id=self.ref(collection, doc, 'location', 'locations'),
            )
            if has_game:
                refs['game_id'] = self.ref(collection, doc, 'game', 'games')
            if not self.required(collection, doc, *required) or None in refs.values():
                continue
            row = self.insert(collection, doc, Model(
                **refs,
                **self.present(doc, 'category', 'quantity', 'borrowing_count', 'sticker_printed', 'images', *own),
            ))
            db.session.add(LegacyObjectId(object_id=str(doc['_id']), item_type=item_type, item_id=row.id))

    def item_ref(self, item_type, raw_id):
        """New id of an item referenced as (item_type, str(ObjectId)), or None."""
        collection = next((c for t, c, *_ in ITEM_TYPES if t == item_type), None)
        if collection is None or not ObjectId.is_valid(str(raw_id)):
            return None
        return self.ids[collection].get(ObjectId(str(raw_id)))

    def import_borrowings(self):
        fields = ['association', 'borrower', 'item_id', 'item_type', 'action', 'date']
        for doc in self.docs('borrowings', fields):
            item_id = self.item_ref(doc.get('item_type'), doc.get('item_id'))
            if item_id is None:
                # The item was deleted; its events already pointed at nothing.
                self.skipped['borrowings of deleted items'] += 1
                continue
            assoc_id = self.ref('borrowings', doc, 'association', 'associations')
            borrower_id = self.ref('borrowings', doc, 'borrower', 'users')
            if not self.required('borrowings', doc, 'action', 'date') or None in (assoc_id, borrower_id):
                continue
            if doc['action'] not in ('borrow', 'return'):
                self.problem('borrowings', doc, f"unknown action {doc['action']!r}")
                continue
            self.insert('borrowings', doc, Borrowing(
                association_id=assoc_id, borrower_id=borrower_id, item_id=item_id,
                item_type=doc['item_type'], action=doc['action'], date=doc['date'],
            ))

    def import_duplicate_links(self):
        fields = ['association', 'item1_id', 'item1_type', 'item2_id', 'item2_type', 'created_at']
        for doc in self.docs('duplicate_links', fields):
            item1 = self.item_ref(doc.get('item1_type'), doc.get('item1_id'))
            item2 = self.item_ref(doc.get('item2_type'), doc.get('item2_id'))
            if item1 is None or item2 is None:
                # Already invisible in the app: get_duplicate_links skips them.
                self.skipped['duplicate links to deleted items'] += 1
                continue
            assoc_id = self.ref('duplicate_links', doc, 'association', 'associations')
            if assoc_id is None:
                continue
            self.insert('duplicate_links', doc, DuplicateLink(
                association_id=assoc_id,
                item1_id=item1, item1_type=doc['item1_type'],
                item2_id=item2, item2_type=doc['item2_type'],
                **self.present(doc, 'created_at'),
            ))

    def unmigrated_collections(self):
        handled = {'associations', 'games', 'users', 'locations', 'borrowings', 'duplicate_links'}
        handled |= {c for _, c, *_ in ITEM_TYPES}
        return {name: self.mongo[name].estimated_document_count()
                for name in sorted(set(self.mongo.list_collection_names()) - handled)
                if not name.startswith('system.')}


def rename_upload_dirs(uploads_dir, legacy_rows, dry_run):
    """uploads/<category>/<ObjectId>/ -> uploads/<category>/<new id>/."""
    renamed, conflicts = 0, []
    for category in sorted(os.listdir(uploads_dir)):
        category_dir = os.path.join(uploads_dir, category)
        if not os.path.isdir(category_dir):
            continue
        for object_id, item_id in legacy_rows:
            src = os.path.join(category_dir, object_id)
            if not os.path.isdir(src):
                continue
            dst = os.path.join(category_dir, str(item_id))
            if os.path.exists(dst):
                conflicts.append(f'{src} -> {dst} (target exists, left alone)')
                continue
            if not dry_run:
                os.rename(src, dst)
            renamed += 1
    return renamed, conflicts


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('--sqlite', help='target SQLite file (default: the app database)')
    parser.add_argument('--mongo-db', help="source database (default: config.json's mongo.database)")
    parser.add_argument('--uploads-dir', help='rename the photo folders under this directory too')
    parser.add_argument('--skip-orphans', action='store_true',
                        help='leave out items whose association no longer exists')
    parser.add_argument('--dry-run', action='store_true', help='import, report, then roll everything back')
    args = parser.parse_args()

    url = f'sqlite:///{os.path.abspath(args.sqlite)}' if args.sqlite else database_url()
    print(f'target: {url}')

    alembic_cfg = Config(os.path.join(find_project_root(), 'alembic.ini'))
    alembic_cfg.set_main_option('sqlalchemy.url', url.replace('%', '%%'))
    command.upgrade(alembic_cfg, 'head')

    mongo_cfg = load_config()['mongo']
    client = MongoClient(
        host=mongo_cfg['server'], port=27017,
        username=mongo_cfg['user'], password=mongo_cfg['pass'],
        authSource='admin', uuidRepresentation='standard',
    )
    mongo = client[args.mongo_db or mongo_cfg['database']]
    print(f'source: mongodb://{mongo_cfg["server"]}/{mongo.name}')

    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = url
    db.init_app(app)

    with app.app_context():
        non_empty = [t.name for t in db.metadata.sorted_tables
                     if db.session.scalar(select(func.count()).select_from(t))]
        if non_empty:
            sys.exit(f'error: the target database already has data ({", ".join(non_empty)}); '
                     'the import only runs into an empty one.')

        importer = Importer(mongo, skip_orphans=args.skip_orphans)
        importer.run()

        print('\nimported:')
        for table, n in sorted(importer.counts.items()):
            print(f'  {table:<18} {n}')
        for reason, n in importer.skipped.items():
            print(f'skipped {n} {reason}')
        for collection, fields in sorted(importer.unknown_fields.items()):
            if fields - {'_cls'}:
                print(f'warning: {collection} has fields the new schema drops: {", ".join(sorted(fields))}')
        for name, n in importer.unmigrated_collections().items():
            note = ' (no code ever read it)' if name in KNOWN_UNUSED else ''
            print(f'warning: collection {name!r} ({n} documents) is not migrated{note}')

        if importer.problems:
            db.session.rollback()
            print(f'\n{len(importer.problems)} problem(s), nothing was written:', file=sys.stderr)
            for p in importer.problems:
                print(f'  {p}', file=sys.stderr)
            sys.exit(1)

        legacy_rows = db.session.execute(select(LegacyObjectId.object_id, LegacyObjectId.item_id)).all()
        if args.dry_run:
            db.session.rollback()
            print('\ndry run: rolled back.')
        else:
            db.session.commit()
            print('\ncommitted.')

    if args.uploads_dir:
        renamed, conflicts = rename_upload_dirs(args.uploads_dir, legacy_rows, args.dry_run)
        print(f'{"would rename" if args.dry_run else "renamed"} {renamed} photo folder(s) in {args.uploads_dir}')
        for c in conflicts:
            print(f'warning: {c}')


if __name__ == '__main__':
    main()
