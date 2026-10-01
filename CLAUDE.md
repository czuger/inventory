# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Flask + SQLAlchemy (SQLite) inventory manager for a wargaming club ("Les Grognards d'Alsace"). Server-rendered
Jinja templates with Bootstrap 5 (CDN), Discord OAuth login, French/English UI, and PDF sticker/list printing.
Schema migrations are Alembic's. The data used to live in MongoDB (MongoEngine); see "Database" below.

## Commands

```bash
# Create/upgrade the database (data/inventory.sqlite3, or $DATABASE_URL), then run the dev server
alembic upgrade head
python -m inventory.api.app

# Tests (pytest.ini always adds coverage: --cov=inventory, term-missing + htmlcov/)
pytest
pytest tests/test_items.py                                       # one file
pytest tests/test_items.py::TestItemCRUD                         # one class
pytest "tests/test_items.py::TestItemCRUD::test_show[miniature]" # one parametrized case
pytest -k borrow                                                 # by name
pytest --no-cov -q                                               # skip coverage

# Grant/revoke admin (user must have logged in via Discord at least once)
python misc/set_admin.py <discord_username> [--revoke]

# After changing a model: generate a migration, READ it, then apply it
alembic revision --autogenerate -m "what changed"
alembic upgrade head

# One-time MongoDB -> SQLite import (needs `pip install pymongo`; see the script's docstring)
python misc/migrate_mongo_to_sqlite.py --dry-run [--skip-orphans] [--uploads-dir DIR]

# Deploy (see deploy/config.sh for the server settings, all env-overridable)
make setup       # one-time: server layout, docker check, nginx snippet
make deploy      # build for the server's arch, ship the image, restart, health check
make rollback    # back to the previous version (nothing is rebuilt or transferred)
make status      # running container + /health, as seen from the server
make logs        # follow the container logs
make nginx       # re-install the nginx snippet only (after changing URL_PREFIX)
```

`config.json` (gitignored) is required at project root and holds `discord` (client_id/client_secret); a leftover
`mongo` section is only read by `misc/migrate_mongo_to_sqlite.py`. `secret_key.txt` (gitignored) holds the Flask
session key; if missing a random key is generated per process, which silently invalidates sessions. In
production both live in the server's `$REMOTE_DIR/config/` and are bind-mounted read-only — no deploy step reads
or writes them. `inventory/libs/initialization.py` finds them by walking up to the first directory holding
`requirements.txt`, `.git` or `README.md`, which is `/app` inside the image. The database is
`<root>/data/inventory.sqlite3` unless `DATABASE_URL` is set (`database_url()`, used by the app, Alembic and the
scripts alike); `data/` is gitignored and dockerignored.

Tests need no server: `create_app(test=True)` uses `data/inventory_test.sqlite3` (never `DATABASE_URL`), which
`tests/conftest.py` deletes and rebuilds with `alembic upgrade head` at the start of every run.
`tests/test_database.py` fails when a model changed without a migration. pytest-flask pushes a request context
around every test, so a test and the requests its client makes share one SQLAlchemy session; use the
`save`/`reload`/`count`/`first` helpers from `conftest.py` rather than raw session calls.

## Architecture

### Multi-tenant routing via `<slug>`

Every item blueprint is mounted at `/<slug>/<items>` where `slug` is an `Association.slug`.
`register_assoc_hooks(bp)` in `inventory/api/utils.py` wires three things per blueprint:

- a `url_value_preprocessor` that pops `slug`, resolves the `Association`, and stores it in `g.assoc` (404 otherwise);
- a `url_defaults` hook that re-injects `g.assoc.slug`, so `url_for('miniatures.show', id=...)` needs no slug;
- a `before_request` admin gate on the view names `create`, `edit`, `delete`, `upload_image`, `delete_image`, `stickers`.

Consequence: **every query must be scoped** with `.filter_by(association=g.assoc)`, and any new mutating view must
either be named one of the gated view names or do its own admin check. `get_or_404` (`inventory/libs/`) does the
scoping itself: a row of another association is a 404. Item routes take `<int:id>`.

### Eight parallel item types

`miniature, terrain, tablecloth, rulebook, board_game, book, equipment, consumable` — each has its own
`inventory/db/<type>.py` model (one table each), `inventory/api/routes/<type>.py` blueprint, and
`inventory/api/templates/<type>/{list,form,show}.html`. All models share `association, category, quantity,
borrowing_count, sticker_printed, location, images` through `ItemMixin` (`inventory/db/item.py`) and differ only in
a few descriptive fields; `images` is a JSON list of filenames.

Adding or changing an item type means touching **all** of these registries, which are hand-maintained and easy to
miss:

| Where | What |
|---|---|
| `inventory/db/constants.py` | `CATEGORIES` (display names) |
| `inventory/db/models.py` | the import list Alembic sees — a model missing here gets its table dropped by autogenerate |
| `alembic/versions/` | a migration creating the table (`alembic revision --autogenerate`) |
| `misc/migrate_mongo_to_sqlite.py` | `ITEM_TYPES` (only matters for the one-time Mongo import) |
| `inventory/api/item_labels.py` | `get_sticker_lines`, `get_list_row`, `_TYPE_BLUEPRINT_MAP`, `_get_type_model_map` |
| `inventory/api/utils.py` | `_SLUG_TO_TYPE` (URL segment → item type, used to parse pasted duplicate URLs) |
| `inventory/api/routes/print_page.py` | `ITEM_TYPES` (type, category name, model, blueprint name) |
| `inventory/api/app.py` | blueprint registration |
| `inventory/api/translations.py` | `nav_*` keys and any new field labels, in both `fr` and `en` |
| `tests/conftest.py` | `ALL_ITEM_MODELS` |
| `tests/test_items.py` | `ITEM_CONFIGS` (drives the parametrized CRUD/borrow/sticker suite) |

Note the naming mismatches: item type is snake_case (`board_game`), blueprint/URL is plural-ish
(`board_games` / `/board-games`), and `equipment` is identical in all three forms.

### Shared behaviour is registered, not inherited

Route modules stay thin by calling registrar functions from `inventory/api/utils.py`, which attach routes to the
blueprint: `register_image_routes` (upload/delete under `static/uploads/<category_snake>/<item_id>/`),
`register_borrow_routes` (writes a `Borrowing` event and bumps `borrowing_count`),
`register_duplicate_routes` (links two items by pasting the other item's URL), and `register_sticker_routes`
(per-type PDF that also flips `sticker_printed`). Each route module then only defines `index/show/create/edit/delete`.

Borrowing is **event-sourced**: `Borrowing` rows (`action` = `borrow`/`return`) are the record; current status
comes from the latest event via the `get_borrow_status` / `get_borrow_history` template globals in `app.py`.
`borrowing_count` on the item is a denormalized counter kept in sync by those routes.

`DuplicateLink` is undirected — queries must check both `item1_*` and `item2_*` (see `get_duplicate_links` in
`app.py` and `add_duplicate` in `utils.py`).

`Borrowing` and `DuplicateLink` point at items through an `(item_type, item_id)` pair spread over eight tables,
which no foreign key can guard: deleting an item leaves them behind (the templates skip what they cannot resolve).
That is also why every table uses `AUTOINCREMENT` — a reused id would inherit a deleted item's history, links and
upload folder.

### Database

`inventory/db/base.py` holds the `db` (Flask-SQLAlchemy) instance and everything that must apply to every
connection and every table, the app's, Alembic's and the scripts' alike:

- **STRICT tables** (`__table_args__ = STRICT`, or `item_table_args()` for item tables). STRICT only accepts the
  column types INTEGER/TEXT/REAL/BLOB/ANY, so `String`/`DateTime`/`JSON` compile to `TEXT` and `Boolean` to
  `INTEGER` there; the Python types are unchanged. A wrong-typed value is an `IntegrityError`, not silently stored.
- **Pragmas**, set by an `Engine` `connect` listener: `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`
  (SQLite's default is OFF), `busy_timeout=5000` (two gunicorn workers share the file).
- A naming convention for constraints, which Alembic's batch mode needs.

`alembic/env.py` turns foreign keys **off** for the duration of a migration and runs `PRAGMA foreign_key_check`
before committing: SQLite cannot ALTER most things, so batch mode rebuilds tables (copy, drop, rename), and dropping
a referenced table fails with foreign keys on. It also makes each `alembic upgrade` one transaction (sqlite3 would
otherwise autocommit DDL statement by statement). Always generate with `--autogenerate` and read the result.

`legacy_object_ids` maps the MongoDB ObjectId of every imported item to its new id. Stickers printed before the
move encode `/<slug>/<items>/<ObjectId>` in their QR code; the `legacy_item` route in `app.py` (an `objectid` URL
converter) 301-redirects those, and pasted duplicate URLs resolve them too. Never drop that table while such
stickers are still on the shelves. Sessions from the Mongo era (string `user_id`) are logged out.

### Templates and i18n

`app.py`'s `inject_globals` context processor exposes `t` (the translation dict for `session['lang']`, default
`fr`), `lang`, `admin`, and `current_user` to every template. Templates always use `t.<key>` — never hardcode
user-facing strings; add the key to both languages in `inventory/api/translations.py`. Nested dicts exist for
enum-ish values (`t.categories[...]`, `t.materials[...]`).

List and show pages are responsive by duplication: a `d-none d-md-block` table for desktop and a `d-md-none`
card/list rendering for mobile.

### Deployment and URL prefix

`make deploy` builds an image, `docker save`s it, scps the tarball, `docker load`s it on the server, **migrates the
database from the new image** (`python -m inventory.db.migrate`, in a throwaway container) and restarts the
container — no registry. Ported from the sibling `tasks_manager` project, so the two stay recognisable.

- `deploy/config.sh` holds every setting and is sourced by all the others; `deploy/remote.sh` is the **server
  side** and is re-uploaded before every run, so the `docker run` options a rollback uses cannot drift from the
  ones a deploy used.
- Releases are timestamped, `current_version.txt`/`previous_version.txt` record the swap **before** the restart,
  and `make rollback` trades the two files. Pruning happens only after a healthy start.
- The container publishes **no port**. It joins nginx's `nginx-common-network` and Mongo's `mongo-network`
  (hence `docker create` + `network connect` + `docker start` rather than `docker run`, which takes only one
  `--network`), and nginx reaches it by container name. The app no longer uses Mongo: that network is only kept so
  `make rollback` to a pre-SQLite release still works; set `MONGO_NETWORK=''` once none is left.
- Server-owned state under `$REMOTE_DIR`: `config/` (config.json, secret_key.txt), `data/uploads/`, bind-mounted
  over `inventory/api/static/uploads`, and `data/db/`, bind-mounted at `/app/data` (the directory, not the file:
  WAL keeps `-wal`/`-shm` files beside the database). **Those mounts are not optional** — the image is rebuilt from
  scratch every release, so anything written inside the container is lost at the next deploy. Docker creates those
  host directories as `root:root`, which the image's uid 10001 cannot write, so `ensure_data_writable` chowns them
  to 10001 before every migration and start via `docker run --user 0` on the image itself (the daemon is root, so
  this needs no sudo on the server). Getting it wrong is invisible to a deploy: `/health` stays green and only the
  first photo upload (`EACCES`) or the first page (database) 500s.
- Migrations run in `cmd_activate` **before** the version bookkeeping and the restart: a failing one is rolled back
  and leaves the running version untouched. When there is something to apply, the database is first copied to
  `data/db/backups/`. `make rollback` never downgrades — the previous image then runs on the newer schema, which is
  only safe for additive migrations; otherwise restore a backup.

`URL_PREFIX` in `deploy/config.sh` is the single source for the sub-path: it renders the nginx `location` block
*and* is passed to the container as an env var. nginx strips the prefix before proxying, so routing already
matches; `mounted_under()` in `app.py` sets `SCRIPT_NAME` so `url_for()` builds links back under it. PATH_INFO is
deliberately untouched. Two consequences worth remembering:

- Changing the prefix needs `make nginx` **and** `make deploy` — one updates the proxy, the other the app.
- The Discord redirect URI is generated with `url_for(..., _external=True)`, so it includes the prefix and must
  match what is registered on the Discord application exactly — currently
  `https://apps.ieroe.com/inventory/auth/discord/callback`. Its **scheme** depends on gunicorn's
  `--forwarded-allow-ips *` (Dockerfile): nginx is a separate container, so without it gunicorn ignores
  `X-Forwarded-Proto` and the URI comes out as `http://`. `auth.login` logs the URI it sends, so `make logs` shows
  exactly what Discord is being asked to match.

`/health` is registered at the app root and never touches the database: it answers "did gunicorn come up with this
image", which is the only question a deploy can act on. A probe that also failed on a database blip would roll
back a good release.

### PDF generation

`inventory/api/pdf.py` builds sticker sheets (105×57mm, 2×5 on A4, QR code linking to the item's absolute `show`
URL) with raw reportlab canvas drawing, and inventory lists with platypus. `/<slug>/print` (admin-only) offers
three scopes: full, one category, or "new only" (`sticker_printed == False`). Generating stickers **marks items
as printed**, so any code path calling `make_stickers_pdf` should be deliberate about that side effect.
