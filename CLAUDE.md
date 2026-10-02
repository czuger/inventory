# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Rust (axum + sqlx on SQLite) inventory manager for a wargaming club ("Les Grognards d'Alsace"). Server-rendered
minijinja templates with Bootstrap 5 (CDN), Discord OAuth and username/password login, French/English UI, PDF
sticker/list printing. It was a Flask app until October 2026; `MIGRATION_PLAN.md` records the port, and much of the
behaviour (and many comments) is defined as "what Flask did" — keep it that way unless asked. Comments citing Python
files (`inventory/...py`, `tests/test_*.py`) refer to the Flask app, still in git history: `git show 5953f4c^:<path>`.

## Commands

```bash
cargo run -- migrate                 # create/upgrade data/inventory.sqlite3 (or $DATABASE_URL), backing it up first
cargo run                            # serve on $BIND_ADDR (0.0.0.0:8000)
cargo run -- set-admin <username> [--revoke]
cargo run -- set-password <username> [--login NAME]   # interactive prompt
cargo run -- healthcheck             # exit 0 if /health answers (the image's HEALTHCHECK)

make test                            # cargo test + cargo clippy --all-targets -- -D warnings
cargo test --test items              # one integration test file (tests/*.rs)
cargo test test_edit                 # by name
./scripts/sqlx-prepare.sh            # after adding/changing a sqlx::query! — regenerates .sqlx/, commit it

# Deploy (see deploy/config.sh for the server settings, all env-overridable)
make setup | deploy | rollback | status | logs | nginx      # add ENV=staging for the staging instance
```

`config.json` (gitignored; `discord.client_id/client_secret`) and `secret_key.txt` (session signing key; missing →
random key per process, which logs everyone out at each restart) live at the root, found by walking up to the first
directory holding `Cargo.toml`, `.git` or `README.md` (`/app` in the image), or `$INVENTORY_ROOT`. In production both
are mounted read-only from the server's `$REMOTE_DIR/config/`. `data/` (database, photos under `data/uploads`) is
gitignored and dockerignored. Other settings are env vars (README → Settings); a root `.env` is loaded.

## Rules

- `unwrap`/`expect` are denied crate-wide (`Cargo.toml` lints); tests may use them (`clippy.toml`, and each
  `tests/*.rs` allows them). Request paths return `AppError`, whose pages are werkzeug's, byte for byte.
- Never put `\uXXXX` escapes in file content written by tools: they get decoded. Build such strings with `\\u`.
- After a model/query change: `scripts/sqlx-prepare.sh`, then commit `.sqlx/` — builds (and the Docker image) compile
  offline against it. The macros read `SQLX_DATABASE_URL` (`sqlx.toml`), never the app's `DATABASE_URL`.
- Schema changes are new files in `migrations/` (next number). Never edit an applied one: `migrate` refuses a changed
  checksum. Tables SQLite cannot ALTER are rebuilt (see `0002`: keep the AUTOINCREMENT counter across the rebuild).

## Architecture

### Request pipeline (`src/lib.rs`)

`build_app` wraps the router *as one service* (not `Router::layer`, which wraps each route): trace → session
middleware → `web::werkzeug_compat`. axum finishes some responses after route layers ran (the `Allow` of a 405), and
these layers must see the final response. `werkzeug_compat` turns axum's empty 405 into werkzeug's page and answers
`OPTIONS`; `web::add_trailing_slash` routes give werkzeug's 308 for `/<slug>/<items>` without the slash.

### Multi-tenant routing via `<slug>`

Every item route is `/{slug}/{segment}/...` where `slug` is an `Association.slug`. Handlers check in Flask's order
(`handlers/items.rs` doc): `<int:id>` (404) → `association()` (404, `AppError::UnknownAssociation`, which also means
"the session was never read": no `Vary`, nothing written back) → `require_admin` (403) → `scoped_item` (404 for
another association's item) → form fields in the view's order. **Every query must be scoped by association**; a new
mutating route must call `require_admin` (or check login for borrow-like actions). Item ids are `<int:id>`; a
24-hex id on a show URL is an old sticker (`db::legacy`) and gets a 301.

### Eight item types, one implementation

`kinds::ItemKind` is the single registry: `item_type` (`board_game`, stored in borrowings/links), `blueprint`
(`board_games`, endpoint prefix), `segment` (`board-games`, URL), table, category name, flash noun, template dir,
default quantity. `db/items.rs` holds the only runtime-built SQL (one column spec per type; the macros need literal
SQL) and `Item` with `ItemFields` flattened in for templates. Adding a type: `ItemKind` + its arms, `own_columns`,
`from_row`, `form_fields` (handlers/items.rs), `labels.rs`, a migration, templates, translations (`nav_*`),
`CATEGORIES`, and the test configs in `tests/items.rs` / `tests/print.rs`.

Route modules per concern, each registered per kind: `handlers/items.rs` (index/show/create/edit/delete),
`borrow.rs`, `images.rs` (uploads under `UPLOADS_DIR/<category_snake>/<id>/`, names `uuid_<secure_filename>`),
`duplicates.rs`, `print.rs` (per-type stickers + `/{slug}/print/`), `auth.rs`, `app.rs`.

Borrowing is **event-sourced**: `borrowings` rows (`borrow`/`return`) are the record; status is the latest event;
`borrowing_count` is a denormalized counter adjusted in SQL in the same transaction (never below 0).
`duplicate_links` are undirected — query both ends. Neither has a foreign key to items (eight tables), so deleting
an item leaves them behind and pages skip what they cannot resolve; that is why every table is AUTOINCREMENT.

### Templates (`src/templates.rs`)

minijinja with Jinja2-compatible output: a formatter printing `None`/`True`/`False` and escaping like MarkupSafe
(`&#39;`, `&#34;`, `/` untouched), pycompat for `.lower()`/`.replace()`, `TemplateDate` with `strftime`. Templates
are embedded by `build.rs`. Every page goes through the `Page` extractor (`t`, `lang`, `admin`, `current_user`,
`request.blueprint`, `url_for`, `get_flashed_messages`). Templates cannot query: `get_borrow_status`,
`get_borrow_history`, `get_duplicate_links` read `ItemExtras` the handler prefetched (`render_with`). Never hardcode
user-facing strings in templates: add keys to both languages in `i18n/translations.json` (`t.<key>`; nested
`t.categories[...]`, `t.materials[...]`). Flash messages written by handlers are English (inherited).

`urls.rs` holds every endpoint's rule; `url_for` injects the current association's slug for item/print endpoints,
puts extra args in the query string, and prefixes `URL_PREFIX` (nginx strips it before proxying, so routing never
sees it). External URLs use `X-Forwarded-Proto` and `Host` — the Discord redirect URI must match the one registered
(`https://apps.ieroe.com/inventory/auth/discord/callback`).

### Sessions and accounts

`session.rs` is Flask's signed cookie (itsdangerous: HMAC-SHA1, tagged JSON, zlib, 31-day max age), readable by
both apps, now `SameSite=Lax`; name/path follow `URL_PREFIX` (`session_<prefix>`) so instances on one host don't
clash. A non-integer `user_id` (Mongo era) is dropped. Discord login keeps authlib's state format in the session.
Password accounts (`password.rs`): argon2id, `users.login` unique case-insensitively (separate from `username`, the
display name Discord overwrites), generic failure message, 10 attempts/min per `X-Real-IP` (set by nginx; never trust
`X-Forwarded-For` for this). Admin is CLI-only.

### Database

`db/mod.rs` sets the pragmas on every connection: WAL, `synchronous=NORMAL`, `foreign_keys=ON`, 5s busy timeout.
Every table is STRICT. Datetimes are TEXT `YYYY-MM-DD HH:MM:SS.ffffff` (always 6 digits — `db::types`; ordering
relies on it) and `images` is `json.dumps` text (`["a", "b"]`). `migrate.rs` runs migrations with foreign keys off,
`PRAGMA foreign_key_check` before each commit, a `VACUUM INTO` backup first, and baselines a database Alembic built
(revision `7b1fd3535193`) as migration 0001.

### PDFs (`src/pdf/`)

A small PDF writer with the built-in Helvetica fonts (WinAnsi) and reportlab's width tables, so wrapping and page
breaks match what reportlab produced (tests pin page counts measured with it). Stickers 105×57mm, 2×5 on A4, QR
codes encoded like Python's `qrcode` (byte mode, level M, smallest version). **Generating stickers marks the items
printed** — be deliberate about that side effect; the list does not.

### Deployment

`make deploy` builds the image (multi-stage `Dockerfile`; `SQLX_OFFLINE`, no database at build time), ships it with
`docker save`/scp, **migrates from the new image** (`inventory migrate` in a throwaway container) and restarts — no
registry. `deploy/remote.sh` is the server side and the single source of the `docker run` options for deploys and
rollbacks; keep it working for the previous image too:

- photos stay mounted at `/app/inventory/api/static/uploads` (the Python image's path; the Rust image sets
  `UPLOADS_DIR` to it), and the health probe falls back to python — so `make rollback` to a Python release works;
- `BIND_ADDR` comes from `APP_PORT`; nginx reaches the container by name on `nginx-common-network`, no port published;
- the database directory (`data/db`, not the file: WAL) is mounted at `/app/data`; mounts are chowned to uid 10001
  before every migration and start; migrations run before the version swap, so a failed one leaves the old version up;
  rollbacks never downgrade (restore a backup from `data/db/backups/` instead).

Two instances, production and staging (`ENV=staging`), derive every name from `APP_NAME` in `deploy/config.sh`.
`URL_PREFIX` there renders the nginx `location` and is passed to the container: changing it needs `make nginx` and
`make deploy`. `/health` never touches the database: it answers "did this image come up", the only question a deploy
can act on.
