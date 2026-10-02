# MIGRATION_PLAN.md — porting the inventory app from Flask to Rust

> **Revision 2 (2026-10-01).** Python is abandoned and removed at the end (Phase 6), with the Rust project moved
> to the repo root. Username/password login is added next to Discord (Phase 5, §5.9).

## Context

The app is the Grognards d'Alsace inventory: Flask 3 + SQLAlchemy 2 + Alembic on SQLite (STRICT tables, WAL),
Jinja templates, Discord OAuth and reportlab PDFs. You want a functionally equivalent Rust version in `./rust/`
that runs against the **existing** database file without data loss and keeps URLs, status codes, redirects and
rendered output the same. The Python app stays untouched until the parity check (Phase 4) is done, then it is
removed (Phase 6).

How the codebase differs from the template prompt (each point drives a decision below):

- **There is no JSON API.** Every response is server-rendered HTML, a redirect (302/301/308), a PDF, plain text
  (`/health`, `/`), or a static file. "Response shape" therefore means status, `Location`, `Content-Type`,
  `Set-Cookie` (decoded session), HTML body (normalised), and PDF content (text and structure).
- **There are no passwords.** Login is Discord OAuth2 (`identify` scope, through authlib). Users are matched on
  `discord_id`.
- **Sessions are Flask's signed client-side cookie** (itsdangerous). This holds `user_id`, `lang`, `_flashes`
  and authlib's OAuth state.
- **Config comes from files, not env vars:** `config.json` (Discord client id/secret) and `secret_key.txt`,
  found by walking up to the project root. Only `DATABASE_URL` and `URL_PREFIX` are env vars.
- **Size:** about 107 routes. 8 item blueprints × 12 routes is 96 of them, the rest are print (3), auth (3), app
  (4) and static. There are 15 tables and 69 Python tests.

### Decisions you made (2026-10-01)

1. **Sessions:** a Flask-compatible signed cookie implemented in Rust, not tower-sessions. Nobody is logged out
   at cutover, rolling back to the Python image stays seamless, and the parity script can send one cookie to both
   apps.
2. **Config:** read the same `config.json` and `secret_key.txt` with the same root-discovery logic. Keep the
   existing env vars (`DATABASE_URL`, `URL_PREFIX`) and add new ones (`BIND_ADDR`, `UPLOADS_DIR`,
   `INVENTORY_ROOT`). dotenvy loads an optional `.env`. The deploy's bind mounts stay valid.
3. **Quirks are fixed, not reproduced.** Each fix is listed in §6.3, and the parity script whitelists exactly
   those differences.
4. **Password login:** username + password only. No email, no password reset, no "remember me". Anyone can create
   an account through a **public sign-up form**. An existing Discord account can also get a password through the
   CLI (`set-password`), and it keeps its borrowing history.
5. **Python goes away at the end.** The Python app and the misc/ `.py` scripts are deleted. The data files in
   misc/ (the xlsx workbook, the mapping JSON, the audit report) are kept. The Rust project moves from `rust/` to
   the repo root. The deploy scripts are switched to the Rust image.

The parity check (Phase 4) still runs **before** the password feature and before any removal, while both apps
exist and behave the same.

---

## 1. Route inventory

Conventions:

- `S` is `/<slug>`, an `Association.slug`. An unknown slug is **404**, checked before anything else
  (`url_value_preprocessor`, `inventory/api/utils.py:65`).
- **admin**: not logged in, or not an admin, gives **403**. **login**: anonymous gives **401**.
- Order of checks: slug 404 → admin 403 / login 401 → `get_or_404` 404 → missing form key 400 (werkzeug
  `BadRequestKeyError`).
- Every item route takes `<int:id>`. An id of another association, or an id that does not exist, gives 404
  (`inventory/libs/get_or_404.py`).
- Redirects are 302 with werkzeug's HTML body and a **relative** `Location`.
- Flask adds `HEAD` to every GET route and `OPTIONS` to every route automatically. A wrong method gives 405 with
  an `Allow` header.
- A rule ending in `/` that is requested without the slash gives **308** to the slashed URL (strict_slashes).

### 1.1 App-level routes (`inventory/api/app.py`, `create_app`)

| Method | Path | Auth | Inputs | Output | Function |
|---|---|---|---|---|---|
| GET | `/` | – | – | 302 → `miniatures.index` of the **lowest-id** association. If there is none, 404 with text `No association found.` (text/html) | `index` |
| GET | `/health` | – | – | 200 `ok`, `text/plain`. Never touches the DB | `health` |
| GET | `/set-language/<lang>` | – | `lang` in {`en`,`fr`}, anything else ignored | sets `session['lang']`, 302 → `Referer` or `/` | `set_language` |
| GET | `/<slug>/<items>/<objectid>` | – | `objectid` = `[0-9a-f]{24}`, `items` = URL segment | 301 → `<bp>.show` of the new id via `legacy_object_ids`. 404 if the type is unknown, the id is unknown, or the type does not match. **The slug is not validated** | `legacy_item` |
| GET | `/static/<path:filename>` | – | – | Flask static file, which includes `uploads/<category_snake>/<id>/<file>` | Flask built-in |

`before_request load_current_user` (app-wide) works like this:

- It reads `session['user_id']`.
- A non-int value is a Mongo-era session: it is popped, which logs the user out and re-sets the cookie.
- Otherwise it sets `g.current_user = User | None`.

### 1.2 Auth (`inventory/api/routes/auth.py`, blueprint `auth`, prefix `/auth`)

| Method | Path | Auth | Inputs | Output | Function |
|---|---|---|---|---|---|
| GET | `/auth/discord` | – | – | 302 → `https://discord.com/api/oauth2/authorize?response_type=code&client_id=…&redirect_uri=<external url_for(auth.callback)>&scope=identify&state=…`. The state is stored in the session. The redirect URI is logged | `login` |
| GET | `/auth/discord/callback` | – | `code`, `state` | Exchanges the code, then GETs `users/@me`. It upserts the `User` (new: `discord_id`, `username`, `display_name = global_name or None`; existing: updates only if the username or display_name changed). Sets `session['user_id']`, 302 → `/` | `callback` |
| GET | `/auth/logout` | – | – | pops `user_id`, 302 → `/` | `logout` |

### 1.3 Item blueprints (×8)

The routes are built by `register_*` helpers in `inventory/api/utils.py`, plus the per-type modules in
`inventory/api/routes/<type>.py`.

| Type (`item_type`) | Blueprint | URL segment | Table | Category name | Flash noun | Default qty |
|---|---|---|---|---|---|---|
| miniature | `miniatures` | `miniatures` | `miniatures` | Miniature | Miniature | 1 |
| terrain | `terrains` | `terrains` | `terrains` | Terrain | Terrain | 1 |
| tablecloth | `tablecloths` | `tablecloths` | `tablecloths` | Tablecloth | Tablecloth | 1 |
| rulebook | `rulebooks` | `rulebooks` | `rulebooks` | Rulebook | Rulebook | 1 |
| board_game | `board_games` | `board-games` | `board_games` | Board Game | Board game | 1 |
| book | `books` | `books` | `books` | Book | Book | 1 |
| equipment | `equipment` | `equipment` | `equipment` | Equipment | Equipment | 1 |
| consumable | `consumables` | `consumables` | `consumables` | Consumable | Consumable | **0** |

Below, `P` = `S/<segment>`.

| Method | Path | Auth | Inputs | Output | View |
|---|---|---|---|---|---|
| GET | `P/` | – | – | `<type>/list.html` with every item of the association | `index` |
| GET | `P/<int:id>` | – | – | `<type>/show.html` (borrow status/history, duplicates, images) | `show` |
| GET | `P/new` | admin | – | `<type>/form.html` with `obj=None` and the refs (§1.5) | `create` |
| POST | `P/new` | admin | form fields (§1.4) | inserts, flashes `"<Noun> created."` (success), 302 → show | `create` |
| GET | `P/<int:id>/edit` | admin | – | form with `obj=item` (also holds the duplicate form) | `edit` |
| POST | `P/<int:id>/edit` | admin | form fields + `sticker_printed` checkbox | updates, flashes `"<Noun> updated."`, 302 → show | `edit` |
| POST | `P/<int:id>/delete` | admin | – | hard delete, flashes `"<Noun> deleted."`, 302 → index | `delete` |
| POST | `P/<int:id>/images` | admin | multipart `images` (several files) | saves each as `<uuid4>_<secure_filename>` under `uploads/<category_snake>/<id>/` and appends it to `images`. 302 → Referer | `upload_image` |
| POST | `P/<int:id>/images/<filename>/delete` | admin | – | if `filename ∈ images`: deletes the file (if present) and removes it from the list. 302 → Referer | `delete_image` |
| POST | `P/<int:id>/borrow` | **login** (401 checked before 404) | – | inserts `Borrowing(action='borrow')` and sets `borrowing_count += 1`. 302 → Referer | `borrow` |
| POST | `P/<int:id>/return` | **login** | – | inserts `Borrowing(action='return')` and sets `borrowing_count = max(0, n-1)`. 302 → Referer | `return_item` |
| POST | `P/<int:id>/duplicates` | admin (own check, 403 before 404) | `duplicate_url` | see §1.6. 302 → Referer, or show | `add_duplicate` |
| POST | `P/<int:id>/duplicates/<int:link_id>/delete` | admin (own check) | – | deletes the link if it is in this association, flashes `Duplicate link removed.` 302 → Referer, or show | `delete_duplicate` |
| GET | `P/stickers` | admin | – | `application/pdf`, inline, `stickers.pdf`, all items of the type. **Sets `sticker_printed=1` on all of them** | `stickers` |

### 1.4 Create/edit form fields per type

`f[x]` means a required field: missing gives 400. `f.get` means optional.

The fields every type shares:

- `category` = `f[category]`. Any string is accepted, nothing is validated.
- `quantity` = `int(f.get(quantity) or <default qty>)`.
- `location` = `get_or_404(Location, f[location])`. It is scoped to the association, and a non-int value is a
  404.

Edit also sets `sticker_printed = 'sticker_printed' in form`. **An unticked checkbox resets it.**

| Type | Own fields | Empty-value handling |
|---|---|---|
| miniature | `type`=f[], `game`=get_or_404(Game, f[]) (**not** association-scoped), `scale`=f[] | – |
| terrain | `type`, `game`, `scale`, `theater`=f.get('theater', '') | the empty string is stored as `''`, **not NULL** |
| tablecloth | `type`, `material`=f.get or **None**, `game`, `size`=f[], `remarks`=f.get or **None** | the empty string becomes NULL. `material` has a CHECK constraint |
| rulebook | `name`, `game`, `supplement`=checkbox | – |
| board_game | `name`, `universe`=f.get('universe', '') | `''`, not NULL |
| book | `name`, `universe`='', `period`='' (both f.get with a `''` default) | `''`, not NULL |
| equipment | `type` | – |
| consumable | `type`, `unit`=f.get('unit', '') | `''`, not NULL. Default qty is 0 |

On insert, these defaults come from SQLAlchemy `default=`, not from the database: `borrowing_count=0`,
`sticker_printed=False`, `images=[]`, and `quantity` 1, or 0 for consumable.

### 1.5 Template context (refs)

Every page gets `t`, `lang`, `admin`, `current_user`, `request.blueprint`, `get_flashed_messages`,
`url_for`, plus the globals `get_borrow_status`, `get_borrow_history` and `get_duplicate_links`.

The forms also get:

- `default_category`, `categories` (`CATEGORIES`) and `locations` (association-scoped, rowid order);
- `games` (all of them, `ORDER BY name`) for miniature, terrain, tablecloth and rulebook;
- `scales` for miniature and terrain;
- `sizes`, `sizes_inches` and `materials` for tablecloth.

The tablecloth list and show pages also get `sizes_inches`.

### 1.6 `add_duplicate` logic (`utils.py:153`)

The URL is parsed as follows:

- Take the path segments; there must be at least 3.
- `parts[1]` maps through `_SLUG_TO_TYPE` (the type).
- `parts[2]` is either digits (the id) or a 24-hex ObjectId, resolved through `legacy_object_ids` (only if the
  type matches).
- The association slug in the URL is **ignored**.

The outcomes are:

- Invalid → flash `Invalid item URL.` (danger).
- Same item → `Cannot link an item to itself.` (warning).
- An existing link in either direction → `This link already exists.` (warning).
- Target not found, or in another association → `Linked item not found.` (danger).
- Otherwise insert and flash `Suspected duplicate link added.` (success).

All outcomes then redirect to `Referer`, or to `<bp>.show` when there is none.

### 1.7 Print (`inventory/api/routes/print_page.py`, blueprint `print_page`, prefix `S/print`, all **admin**, 403 even on GET)

| Method | Path | Inputs | Output | View |
|---|---|---|---|---|
| GET | `S/print/` | `?category=` (preselect) | `print/index.html` | `index` |
| POST | `S/print/stickers` | `mode` ∈ new/full/category (default `full`), `category` (used only when mode=category) | sticker PDF over the 8 types in `ITEM_TYPES` order. `new` skips printed items. **Marks every included item printed** | `stickers` |
| POST | `S/print/list` | same | list PDF. The title is the category, or `Inventaire`. Does not mark anything | `print_list` |

There are **no background jobs, no CLI inside the app, and no custom error handlers.** Error responses are
werkzeug's default HTML pages.

---

## 2. Database schema → Rust

Every table is `STRICT`. Every integer-PK table is `AUTOINCREMENT` (ids are never reused). Constraint names
follow the naming convention in `inventory/db/base.py`. The authoritative DDL is the Alembic migration
`alembic/versions/2026_10_01_7b1fd3535193_initial_schema.py`. The Alembic-managed table `alembic_version` also
exists.

Physical types under STRICT: `String`, `DateTime` and `JSON` are `TEXT`; `Boolean` is `INTEGER` (0/1).

- **`DateTime`** is stored by SQLAlchemy as text `YYYY-MM-DD HH:MM:SS.ffffff` (always 6 fractional digits,
  naive UTC, `utcnow()` in `base.py:89`). Ordering relies on text order, so Rust **must write exactly this
  format**. sqlx's chrono encoding uses a variable-length fraction, so a `PyDateTime` newtype implements
  Encode/Decode.
- **`JSON`** (`images`) is written by Python as `json.dumps(list)`, i.e. `["a", "b"]` with `", "` separators and
  ASCII escaping. An `ImagesJson` newtype writes the same bytes.

| Table | Columns (all NOT NULL unless marked `?`) | Constraints / indexes | Relationships (ORM) | Rust struct |
|---|---|---|---|---|
| `associations` | id INTEGER PK AI, name TEXT, slug TEXT | `uq_associations_name`, `uq_associations_slug` | – | `Association { id: i64, name: String, slug: String }` |
| `games` | id, name TEXT | `uq_games_name` | – | `Game { id, name }` |
| `users` | id, discord_id TEXT, username TEXT, display_name TEXT?, is_admin INTEGER (default False) | `uq_users_discord_id` | – | `User { id, discord_id, username, display_name: Option<String>, is_admin: bool }` |
| `locations` | id, association_id → associations, room TEXT, spot TEXT (default `''`, never NULL) | `uq_locations_association_id_room_spot` | association | `Location { id, association_id, room, spot }` |
| `legacy_object_ids` | object_id TEXT PK (no AI), item_type TEXT, item_id INTEGER | STRICT only | – | `LegacyObjectId { object_id, item_type, item_id }` |
| `borrowings` | id, association_id → associations, borrower_id → users, item_id INT, item_type TEXT, action TEXT, date TEXT (default utcnow) | `ck_borrowings_action_choices` (`borrow`/`return`), `ix_borrowings_item(item_type,item_id,date)` | association, borrower (User) | `Borrowing { id, association_id, borrower_id, item_id, item_type: ItemKind, action: BorrowAction, date: PyDateTime }` + `borrower: User` when loaded for templates |
| `duplicate_links` | id, association_id → associations, item1_id, item1_type, item2_id, item2_type, created_at TEXT (default utcnow) | `ix_duplicate_links_association_id` | association | `DuplicateLink { … }` |
| **item tables** (8) | id, association_id → associations, category TEXT, *own fields*, quantity INT (default 1, or 0), borrowing_count INT (default 0), sticker_printed INT (default 0), location_id → locations, images TEXT (default `[]`) | `ck_<t>_images_is_array` (`json_type(images)='array'`), `ix_<t>_association_id`, FKs `fk_<t>_<col>_<ref>` | association, location (joined), game (joined, where present) | `ItemCommon { id, association_id, category, quantity: i64, borrowing_count: i64, sticker_printed: bool, location: Location, images: ImagesJson }` + `ItemFields` enum, and `Item { kind: ItemKind, common, fields }` |

Each item table's own fields (the column order of `CREATE TABLE` is preserved):

- `miniatures`: type, game_id→games, scale
- `terrains`: type, game_id, scale, theater?
- `tablecloths`: type, material? (CHECK in `mousepad (neoprene)`/`vinyl`/`cloth`/`textured`), game_id, size, remarks?
- `rulebooks`: name, game_id, supplement INT (default False)
- `board_games`: name, universe?
- `books`: name, universe?, period?
- `equipment`: type
- `consumables`: type, unit?

**Cascades:** none. Deleting an item leaves its `borrowings`, `duplicate_links` and upload folder behind, and the
templates skip what they cannot resolve. Deleting a referenced location or game fails on the FK (there is no UI
for it). There are no `onupdate=`, hybrid properties or ORM event listeners. The only listener is the
per-connection pragma hook.

**Pragmas** on every connection: `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`,
`busy_timeout=5000`. In sqlx these are set through `SqliteConnectOptions`.

---

## 3. Dependencies → crates

| Python | Used for | Rust replacement |
|---|---|---|
| Flask, Werkzeug | routing, request/response, redirects, error pages, multipart, static files | `axum` 0.8 + `tokio`, `tower-http` (`ServeDir`, `TraceLayer`), axum `Multipart`. Werkzeug's error and redirect bodies are reproduced verbatim. `secure_filename` is ported in `upload.rs` (with `unicode-normalization`) |
| Flask-SQLAlchemy, SQLAlchemy | ORM | `sqlx` (sqlite, runtime-tokio, macros, migrate, chrono). `query_as!` with offline `.sqlx/` committed, so builds need no DB |
| alembic | migrations | `sqlx::migrate!` plus a baseline step (§5.4) |
| authlib (+ requests) | Discord OAuth2 client | `oauth2` 5 + `reqwest` (rustls). The Discord base URL is configurable so tests can mock it (`wiremock`) |
| itsdangerous (via Flask) | session cookie signing | own `session.rs`: `hmac` + `sha1` + `base64` + `flate2` + `serde_json` (Flask's tagged JSON for tuples) |
| Jinja2, MarkupSafe | templates | `minijinja` + `minijinja-contrib` (pycompat for `.lower()`/`.replace()`), a markupsafe-compatible auto-escape formatter (§5.2) |
| reportlab | sticker sheet (canvas) and list (platypus table) | `printpdf` with the built-in Helvetica / Helvetica-Bold fonts. A width table is generated once from reportlab's own metrics, so line wrapping matches. The table layout is hand-written (it is small) |
| qrcode[pil], Pillow | QR code as PNG | `qrcode` crate (EcLevel M, quiet zone 1), drawn as vector rectangles. No raster or Pillow equivalent is needed |
| gunicorn | 2 workers, `--forwarded-allow-ips *` | a single tokio multi-thread process on `BIND_ADDR` (default `0.0.0.0:8000`). `X-Forwarded-Proto` is trusted unconditionally, like gunicorn's `*` |
| pytest, pytest-flask, pytest-cov | tests | `cargo test`, `tower::ServiceExt::oneshot`, `tempfile`, `wiremock`. `cargo llvm-cov` is optional |
| logging | logs | `tracing` + `tracing-subscriber` (env-filter) |
| – | errors / CLI | `thiserror` (one `AppError: IntoResponse`), `anyhow` in `main` only, `clap` |
| – | config | `serde_json` for `config.json`, `dotenvy` |
| uuid (stdlib) | upload filenames | `uuid` v4 |
| – (new, Phase 5) | password login | `argon2` (argon2id, PHC strings), `rpassword` (CLI prompt) |

---

## 4. Framework features in use

These are the Flask extensions, blueprints, hooks and scripts the Rust port has to replace.

- **Extensions:** Flask-SQLAlchemy and authlib `OAuth`. Nothing else: no Flask-Login, no WTForms, no CSRF.
- **Blueprints:** auth, 8 item blueprints, print_page.
- **Hooks:**
  - app `before_request` (load the user);
  - `context_processor` (`t`, `lang`, `admin`, `current_user`);
  - 3 `template_global`s that **query the DB from inside the templates**;
  - per blueprint: `url_value_preprocessor` (slug → `g.assoc`), `url_defaults` (re-inject the slug), and
    `before_request` (admin gate by view name);
  - print_page's own `before_request`.
- **URL converter:** `objectid`.
- **Middleware:**
  - `mounted_under` sets `SCRIPT_NAME` from `URL_PREFIX`, which only affects generated URLs;
  - the session cookie is named `session_<prefix>` with path `/<prefix>` when a prefix is set;
  - logging is configured with `basicConfig` at DEBUG.
- **Scripts outside the app:**
  - `misc/set_admin.py` (ported as a CLI subcommand);
  - `python -m inventory.db.migrate` (backup, then upgrade; ported);
  - `misc/migrate_mongo_to_sqlite.py`, `misc/seed_grognards.py` and the xlsx scripts are not ported. They are
    one-off tools and are deleted in Phase 6, and their data files are kept.

---

## 5. Hard parts and how they are handled

### 5.1 Template globals that hit the DB

minijinja functions are synchronous and sqlx is async. The **show and edit handlers prefetch** the item's borrow
status, history and duplicate links. They then register `get_borrow_status`, `get_borrow_history` and
`get_duplicate_links` for that render as closures that return the prefetched data when called with the page's own
`(item.id, item_type)`. The templates stay unchanged. A call with any other arguments logs a warning and returns
none or empty.

### 5.2 Jinja2 → minijinja differences

The templates are **copied** to `rust/templates/` (the Python copy is not touched). Known gaps:

| Construct | Fix |
|---|---|
| `{% if self.title() %}` in `base.html` | Edit the template. Every child defines a non-empty title, so the result is identical |
| `.lower()`, `.replace()` (16×) | `minijinja-contrib` pycompat callback, no template change |
| `b.date.strftime('%Y-%m-%d %H:%M')` | Datetimes are a minijinja `Object` with a `strftime` method, no template change |
| autoescape: markupsafe writes `&#39;` and `&#34;` and leaves `/` alone; minijinja writes `&#x27;` and `&#x2f;` | a custom formatter that copies markupsafe |
| `None` renders as `None` and booleans as `True`/`False` in Jinja | the same formatter |
| `{% set %}` inside `{% if %}` then used outside it (`show.html:4`) | check minijinja's scoping in the miniature slice; if it differs, edit the template |
| `get_flashed_messages(with_categories=true)`, `request.blueprint`, `url_for(endpoint, **kw)` | Rust functions. `url_for` handles slug injection, extra kwargs → query string, `_external`, the `SCRIPT_NAME` prefix, and the `static` endpoint |
| `{% with %}`, `{% for %}…{% else %}`, `~`, `\|string`, dict indexing | supported as is |

### 5.3 Flask session cookie

Format: `base64url(json)` or `.` + `base64url(zlib(json))`, then `.` + timestamp, then `.` + signature.

- The signature is HMAC-SHA1 with key = HMAC-SHA1(secret, `"cookie-session"`).
- Tuples use Flask's tagged JSON `{" t": [...]}`, which is how flashes are stored.
- The max age is 31 days (Flask applies `PERMANENT_SESSION_LIFETIME` even to non-permanent sessions).
- Cookie attributes: `HttpOnly`, no `Secure`, no `SameSite`, no expiry. Name and path depend on the prefix.
- `Vary: Cookie` is sent when the session is read.
- An emptied session deletes the cookie (`Max-Age=0`).

A unit test decodes a fixture cookie signed by Python's itsdangerous, and Python must decode a cookie signed by
Rust. Both are checked in the parity script.

### 5.4 sqlx migrations against an Alembic database

`migrations/0001_initial_schema.sql` is **dumped from `sqlite_master` of a database built by `alembic upgrade
head`**, not hand-written. A test compares the normalised `sqlite_master` of a sqlx-migrated DB against that
dump.

The `migrate` subcommand works as follows:

1. **Baseline.** If `alembic_version` = `7b1fd3535193` and `_sqlx_migrations` is absent, it creates
   `_sqlx_migrations` and records 0001 as applied, with sqlx's own checksum. `alembic_version` is left in place
   until Phase 6, so both apps can share a database copy during the parity check. Phase 6 drops it in a
   migration.
2. **Backup first.** It backs up with `VACUUM INTO data/db/backups/<ts>-before-<version>.sqlite3`, which is a
   consistent copy that includes the WAL, as `inventory/db/migrate.py` does today.
3. **Migrate.** It runs the migrations on a connection with `foreign_keys=OFF`, then runs
   `PRAGMA foreign_key_check`, as `alembic/env.py` does.

The server does **not** auto-migrate at startup, which matches the deploy.

### 5.5 Eight parallel item types

A single `ItemKind` enum carries all the metadata from §1.3 and replaces the 11 hand-maintained registries listed
in CLAUDE.md. The handlers are written once and generic over `ItemKind`, which is passed through router state.

The compile-time-checked SQL is per table, so a `macro_rules!` generates the 8 query sets. Each list is
`ORDER BY id`: Python issues no ORDER BY and gets rowid order, and the parity check confirms they match.

### 5.6 Routing edge cases

axum's static segments win over parameters, so `S/miniatures/{id}` would also catch a legacy ObjectId. The show
handler therefore does three things:

- digits → show the item;
- `[0-9a-f]{24}` → the legacy 301;
- anything else → 404.

A generic `/{slug}/{items}/{oid}` route handles the other cases. A fallback layer reproduces strict-slash 308s,
auto `OPTIONS` and 405 with `Allow`.

The integer parsing of form values follows Python's `int()`: it strips whitespace and accepts a sign and `_`
separators, and negative quantities are accepted, as today.

### 5.7 PDFs

Byte-identical output is impossible because reportlab embeds timestamps and ids. Parity is defined as:

- same page count;
- same text per page (via `pdftotext`);
- same sticker grid (105×57mm, 2×5, the same margins and wrapping);
- QR codes that decode to the same URLs.

Risk: non-ASCII characters (`é`, `–`) with printpdf's built-in fonts. The plan is WinAnsi encoding. If that is
not reliable, the fallback is to embed a metric-compatible font (Liberation Sans).

### 5.8 Behaviour that must not drift

- Making stickers marks items as printed; editing an item resets the flag unless the checkbox is ticked.
- `borrowing_count` never goes below 0.
- Borrowing order is `date DESC, id DESC`.
- `DuplicateLink` is queried in both directions.
- Upload paths are `category.lower().replace(' ', '_')`.
- Legacy ObjectId redirects keep working.
- `/health` never touches the DB.
- `URL_PREFIX` is ignored in tests.
- External URLs use `X-Forwarded-Proto` and the `Host` header, so the Discord redirect URI stays
  `https://apps.ieroe.com/inventory/auth/discord/callback`.

### 5.9 Username/password login (new feature, Phase 5)

**Schema: migration `0002_password_login.sql`.** SQLite cannot drop a NOT NULL constraint, so `users` is rebuilt
(copy, drop, rename) with foreign keys off and a `foreign_key_check` afterwards, as in §5.4. Ids are preserved, so
`borrowings.borrower_id` stays valid.

| Column | Change | Why |
|---|---|---|
| `discord_id` | becomes nullable (still `UNIQUE`; SQLite allows several NULLs) | a sign-up user has no Discord account |
| `login TEXT` | new, nullable, unique index `uq_users_login` with `COLLATE NOCASE` | the name typed on the login form |
| `password_hash TEXT` | new, nullable | an argon2id hash |
| CHECK `ck_users_has_credentials` | new: `discord_id IS NOT NULL OR (login IS NOT NULL AND password_hash IS NOT NULL)` | every user can log in some way |

`login` is a separate column from `username` on purpose:

- `username` stays the display name. Discord overwrites it on every login, and it is not unique.
- If the login name lived in `username`, a Discord user renaming themselves to an existing login name would break
  the callback with a unique violation, and a sign-up could take the name of a Discord member who has not logged
  in yet.
- With a separate column, the Discord flow is untouched.

Sign-up sets both `login` and `username` to the chosen name. `User` in Rust gains
`discord_id: Option<String>`, `login: Option<String>` and `password_hash: Option<String>`. The hash is never sent
to a template.

**Hashing.** argon2id via the `argon2` crate, with its default parameters, stored as a PHC string
(`$argon2id$v=19$…`). Hashing and verifying run in `spawn_blocking`. When the login name is unknown, a dummy hash
is still verified, so response time does not reveal which names exist.

**Routes** (blueprint `auth`):

| Method | Path | Auth | Inputs | Output |
|---|---|---|---|---|
| GET | `/auth/login` | – | – | `auth/login.html`: the login form, a "Log in with Discord" button (→ `/auth/discord`) and a link to sign up |
| POST | `/auth/login` | – | `username`, `password` | success: `session['user_id']`, 302 → `/`. Failure: the form again with **400** and one generic message, `t.invalid_credentials` (unknown name, wrong password, or an account without a password all look the same) |
| GET | `/auth/register` | – | – | `auth/register.html` |
| POST | `/auth/register` | – | `username`, `password`, `password_confirm` | validates, creates a non-admin user, logs them in, 302 → `/`. Failure: the form again with **400**, the error, and the username kept |
| GET | `/auth/logout` | – | – | unchanged |

**Validation on sign-up:**

- `username` is trimmed. It must be 3–32 characters from letters, digits, `_`, `.` and `-`, and not already used
  as a `login` (case-insensitive).
- `password` must be 8–128 characters and equal to `password_confirm`.
- Each failure has its own translated message.

**Login from the CLI.** `inventory set-password <username> [--login <name>]` works on any user, Discord or not.
It prompts twice for the password with `rpassword`, so the password never appears in the shell history. If the
user has no `login`, it uses `--login`, or else the username. It errors when the username matches several users.
`set-admin` gets the same "ambiguous username" check.

**UI and i18n.**

- In `base.html`, the Discord icon button becomes a link to `/auth/login`.
- New `fr`/`en` keys: `login`, `register`, `username`, `password`, `password_confirm`, `login_with_discord`,
  `no_account`, `have_account`, `invalid_credentials`, `username_invalid`, `username_taken`,
  `password_too_short`, `passwords_mismatch`.
- New messages are translated. The existing hardcoded English flashes stay as they are.

**Abuse protection.** This is kept simple, but a public sign-up on a public URL needs some.

- **Rate limit.** An in-memory per-IP limiter (client IP from `X-Forwarded-For`, set by nginx) allows 10 POSTs
  per minute across `/auth/login` and `/auth/register`, and answers 429 beyond that.
- **Cookie.** The session cookie gains `SameSite=Lax`. Every mutating route is a POST, so this blocks cross-site
  form posts. The app has never had CSRF protection; this is now possible because no Flask app has to read the
  same cookie.
- **Admin rights.** New users are never admins; admin stays CLI-only.
- **Borrowing is open to anyone who signs up.** Borrowing already only requires being logged in, so this widens
  who can borrow. That is the consequence of choosing a public sign-up.

---

## 6. Rust project

### 6.1 Layout

The project lives in `rust/` until Phase 6, which moves it to the repo root.

```
rust/
  Cargo.toml   .sqlx/   Dockerfile   build.rs (none unless needed)
  migrations/0001_initial_schema.sql
  migrations/0002_password_login.sql   # Phase 5
  migrations/0003_drop_alembic_version.sql   # Phase 6
  templates/                 # copied from inventory/api/templates, edits listed in §5.2; + auth/login.html, auth/register.html
  static/                    # favicon etc.; /static/uploads/* is served from UPLOADS_DIR
  i18n/translations.json     # generated once from translations.py, embedded with include_str!
  src/
    main.rs                  # clap: serve (default) | migrate | set-admin <user> [--revoke] | set-password <user> [--login] | healthcheck
    password.rs              # argon2id hash/verify, sign-up validation, rate limiter
    lib.rs                   # build_app(AppState) -> Router, used by main and the tests
    config.rs                # root discovery (Cargo.toml/.git/README.md or INVENTORY_ROOT), config.json, secret_key.txt, env
    error.rs                 # AppError (thiserror) -> werkzeug-identical error pages
    db/{mod.rs, types.rs (PyDateTime, ImagesJson), models.rs, items.rs, borrowings.rs,
        duplicates.rs, legacy.rs, refs.rs (associations, games, locations, users)}
    migrate.rs               # baseline + backup + run + foreign_key_check
    session.rs               # Flask cookie codec, flashes, Session extractor and response layer
    extract.rs               # CurrentUser, Assoc (slug), RequireAdmin, RequireLogin, Referer, ExternalBase
    urls.rs                  # endpoint registry, url_for, prefix, strict-slash fallback
    templates.rs             # minijinja env, formatter, pycompat, globals, context builder
    kinds.rs                 # ItemKind and its metadata table
    labels.rs                # get_sticker_lines, get_list_row, get_item_display
    upload.rs                # secure_filename, save/delete under UPLOADS_DIR
    pdf/{stickers.rs, list.rs, metrics.rs, qr.rs}
    handlers/{app.rs, auth.rs, items.rs, images.rs, borrow.rs, duplicates.rs, stickers.rs, print.rs}
  tests/
    common/mod.rs            # temp DB file + migrate + seed, cookie forging, request helpers
    items.rs  borrowing.rs  duplicates.rs  print.rs  auth.rs  password_auth.rs  database.rs  schema.rs
  parity/run_parity.py       # Phase 4
```

`#![cfg_attr(not(test), deny(clippy::unwrap_used, clippy::expect_used))]` is set in `lib.rs`. `main.rs` uses `?`
with `anyhow`.

### 6.2 Config and environment

| Setting | Source | Default |
|---|---|---|
| Discord client id/secret | `config.json` `discord.*` | required |
| Session key | `secret_key.txt` | random key per process, with an error logged (as today) |
| `DATABASE_URL` | env | `<root>/data/inventory.sqlite3`. Both `sqlite:///abs` (SQLAlchemy) and sqlx forms are accepted |
| `URL_PREFIX` | env | none |
| `BIND_ADDR` | env (new) | `0.0.0.0:8000` |
| `UPLOADS_DIR` | env (new) | until Phase 6: `<root>/inventory/api/static/uploads`, shared with Python. From Phase 6: `<root>/data/uploads`, mounted at `/app/data/uploads` in the container |
| `INVENTORY_ROOT` | env (new) | root discovery. Markers: `Cargo.toml`, `.git`, `README.md` (requirements.txt goes away). The container puts a marker in `/app` |
| `RUST_LOG` | env | `info` |

### 6.3 Quirks fixed in the port (whitelisted in Phase 4)

| Python behaviour | Rust |
|---|---|
| borrow, return, upload or delete-image without a `Referer` → 500 (`redirect(None)`) | 302 → the item's show page |
| non-numeric `quantity` → 500 (`ValueError`) | 400 |
| invalid tablecloth `material` → 500 (`IntegrityError`) | 400 |
| OAuth callback with `?error=…`, a state mismatch, or a failed token exchange → 500 | 302 → `/` with the danger flash `Discord login failed.` (→ `/auth/login` once it exists, Phase 5) |
| a pasted duplicate URL under the production prefix (`/inventory/<slug>/<items>/<id>`) was refused as `Invalid item URL.` | the prefix is stripped first, so the link is made |
| list PDF: item names went through reportlab's `Paragraph` markup parser (`<b>`, `&amp;` were interpreted) | names are printed literally |
| session cookie without `SameSite` | `SameSite=Lax` (Phase 5, §5.9) |

---

## 7. Porting steps, in order

**Phase 2: scaffolding**

- [x] 1. `cargo new rust` with dependencies, the lint config, `rustfmt`, and clippy `-D warnings`
- [x] 2. `config.rs` and tracing setup
- [x] 3. Schema:
  - dump the Alembic schema into `migrations/0001` and a test fixture;
  - create the pool with the pragmas;
  - add the `migrate` subcommand (baseline, backup, FK check);
  - add `tests/schema.rs`, which checks the schema against Alembic, plus the pragmas, STRICT, FK enforcement
    and no id reuse
- [x] 4. `AppError` and werkzeug error pages, `GET /health`, the `healthcheck` subcommand. `cargo build`, clippy
  and tests pass

  *Done 2026-10-01. Notes from this phase:*
  - *The resolver picked **sqlx 0.9.0**. It is used as planned, with `AssertSqlSafe` wherever SQL is built at
    runtime.*
  - *`migrate` reuses sqlx's own bookkeeping table and row format (`ensure_migrations_table`, and `skip` for the
    Alembic baseline). It applies each migration in its own loop, so `PRAGMA foreign_key_check` runs before each
    commit.*
  - *Compile-time-checked queries (`query_as!` and an offline `.sqlx/`) arrive with the first real queries, in
    step 7. Phase 2 has only bookkeeping and test SQL.*
  - *Lints: `unwrap_used` and `expect_used` are denied crate-wide in `Cargo.toml`. `clippy.toml` allows them in
    tests.*

**Phase 3: incremental port**

- [x] 5. Flask-compatible session, flashes, `CurrentUser` and Mongo-era logout, with cross-language cookie
  fixtures
- [x] 6. `url_for`, prefix and strict slashes; the minijinja env, formatter and i18n JSON; `/set-language`, `/`
  and static serving
- [x] 7. Reference queries (associations, games, locations, users) and the generic item framework, plus the
  **miniature** slice: index, show, create, edit, delete, admin gate, cross-association 404, sticker reset on edit
- [x] 8. Terrain
- [x] 9. Tablecloth (the material CHECK becomes a 400, `sizes_inches`)
- [x] 10. Rulebook
- [x] 11. Board game
- [x] 12. Book
- [x] 13. Equipment
- [x] 14. Consumable (default quantity 0)
- [x] 15. Borrowing: borrow/return, the counter floor at 0, history order, prefetched globals
  (tests from `test_borrowing.py` and the borrow cases in `test_items.py`)
- [x] 16. Images: multipart upload, `secure_filename`, delete
- [x] 17. Duplicates, `legacy_object_ids`, the `legacy_item` 301 (`test_duplicates.py` and the legacy tests in
  `test_database.py`)
- [x] 18. PDF: QR code, sticker sheet, list. The per-type `stickers` route and the print page
  (`test_print.py` and `test_stickers_marks_printed`)
- [x] 19. Discord OAuth: login, callback, logout, against a mocked Discord (`test_auth.py`)
- [x] 20. `set-admin` CLI. `rust/Dockerfile` (multi-stage, uid 10001, same in-container paths, `HEALTHCHECK` via
  the `healthcheck` subcommand). The deploy switch itself happens in Phase 6

  *Phase 3 done 2026-10-02 — 152 Rust tests (every Python test has its counterpart), clippy clean.
  Where the implementation departs from the plan above:*
  - *The eight item tables use runtime SQL built from one column spec (`db/items.rs`): the query macros need
    literal SQL, so they stay for the fixed queries (19 of them, `.sqlx/`), and the item queries are exercised
    on every table by the parametrized tests. `scripts/sqlx-prepare.sh` regenerates `.sqlx/`; the macros read
    `SQLX_DATABASE_URL` (`sqlx.toml`), never the app's `DATABASE_URL`.*
  - *PDFs: a small PDF writer (`src/pdf/`) instead of `printpdf`. Built-in Helvetica in WinAnsi with reportlab's
    own width tables; the list layout reproduces platypus to the point (title, row and text coordinates match
    reportlab's to four decimals; page breaks checked against reportlab at 7 boundaries). QR codes are encoded
    like Python's `qrcode` (byte mode, EC level M, smallest version), drawn as vectors.*
  - *Discord: `reqwest` directly rather than the `oauth2` crate — the flow is two requests, and authlib's exact
    authorize URL and session state format are reproduced. `DISCORD_API_BASE` (new) lets tests use a mock.*
  - *Templates are embedded by `build.rs` (no `minijinja-embed`, whose loader panics on a broken template).*
  - *Early HTML parity check (111 GET requests across all page types and three sessions): byte-identical.*
  - *The Docker image could not be built here (no Docker daemon running); it is untested until Phase 6.*

Each slice runs `cargo build && cargo clippy -- -D warnings && cargo test` and then ticks its box. Every Python
test has a Rust counterpart with the same name: `test_items.py` is parametrized over all 8 types, so its Rust
version is a macro over `ItemKind`.

**Phase 4: parity verification**

- [x] 21. `rust/parity/run_parity.py` does the following:
  - copies a real or seeded DB twice;
  - starts Flask (`gunicorn`) and Rust on two ports with the same `secret_key.txt` and `config.json`;
  - forges anonymous, user and admin cookies with itsdangerous;
  - replays a fixed request script against both, for every route in §1 and both languages, including 404, 403,
    401, 405 and 308 cases and the mutating POSTs in the same order;
  - diffs the status, `Location`, `Content-Type`, the decoded session from `Set-Cookie`, the normalised HTML
    and the PDF text, page count and QR URLs;
  - finally diffs both databases table by table (timestamps and uuid filenames normalised).

  §6.3 differences are whitelisted.
- [x] 22. Fix every remaining difference and write a report of anything left intentionally.

  *Phase 4 done 2026-10-02. `python rust/parity/run_parity.py` → **PARITY OK**: 370 requests over two passes
  (no prefix, and `URL_PREFIX=inventory`), 0 unexpected differences in status, headers, session, body or final
  database; the 6 expected ones are the §6.3 fixes. What it found and got fixed on the way:*
  - *an unknown association slug: Flask answered before reading the session, so no `Vary: Cookie` and no
    Mongo-era clean-up on that request (`AppError::UnknownAssociation`);*
  - *static files and photos carry Flask's `Content-Disposition: inline; filename=…`.*

  *What the comparison does not cover, and why that is acceptable:*
  - *QR codes are not decoded (no zbar here). The Rust tests pin the encoding parameters against Python's
    `qrcode` (byte mode, level M, same version); the mask may differ, the content cannot.*
  - *PDFs are compared by page count and drawn text, not bytes (reportlab embeds ids and dates). The list's
    geometry was checked separately against reportlab's coordinates.*
  - *Not compared: `Date`, `Server`, `Content-Length`, and the caching headers of static files (`ETag`,
    `Last-Modified`), which only affect browser caching. A compressed session cookie can differ in bytes (zlib
    implementations) while decoding to the same session; both apps read both.*
  - *A successful Discord login needs Discord itself: covered by the mocked tests (`tests/auth.rs`).*
  - *Item names containing markup (`<…>`, entities) print literally in the list PDF now (§6.3); the script
    strips tags on both sides before comparing.*

**Phase 5: username/password login (§5.9)**

- [x] 23. Migration `0002_password_login.sql`, which rebuilds `users`. A test runs it on a copy of a baselined
  database (built from the real Alembic schema, seeded with users and borrowings) and checks that ids, rows and
  borrowings are unchanged
- [x] 24. `password.rs`: hashing, validation, rate limiter. `User` gets its new fields. `SameSite=Lax` on the
  cookie
- [x] 25. Login and register routes and templates. The navbar link. The i18n keys in `fr` and `en`
- [x] 26. `set-password` CLI, and the "ambiguous username" check in `set-admin`
- [x] 27. `tests/password_auth.rs`, covering:
  - sign-up: success (logged in, not admin), name taken (any letter case), invalid name, short password,
    mismatched confirmation;
  - login: success, wrong password, unknown name, Discord-only account;
  - a Discord user given a password with `set-password` can log in both ways and keeps their borrowings;
  - the Discord callback never touches `login` or `password_hash`;
  - the 11th POST in a minute gets a 429;
  - logout.

  *Phase 5 done 2026-10-02 — 166 Rust tests. Departures from §5.9:*
  - *The limiter keys on `X-Real-IP`, not `X-Forwarded-For`: nginx sets `X-Real-IP` from the connection,
    while the first `X-Forwarded-For` entry is whatever the client sent, so it would let anyone dodge the limit.*
  - *Over the limit, the form comes back with a 429 and a translated message rather than a bare error page.*
  - *A failed Discord login now lands on `/auth/login` (which offers both ways in) instead of `/`.*
  - *`set-password` needs a terminal (`docker exec -it` in production) and says so when there is none.*
  - *Migration 0002 keeps the AUTOINCREMENT counter of `users` across the table rebuild, so a deleted user's id
    is still never reused (tested).*
  - *From here on `run_parity.py` reports the intended differences (the navbar's login link, the new `users`
    columns): the Phase 4 result above is the one that counts.*

**Phase 6: remove Python and switch the deploy**

- [x] 28. Delete the Python app and its tooling:
  - delete `inventory/`, `tests/`, `alembic/`, `alembic.ini`, `requirements.txt`, `pytest.ini` and every
    `misc/*.py`;
  - keep `misc/20241206_inventaire Grognards.xlsx`, `misc/inventory_v1_mapping.json` and
    `misc/inventory_xlsx_extraction_report.md`.
- [x] 29. `git mv rust/* .` in a commit of its own (only the move, so history stays readable). Migration `0003`
  drops `alembic_version`
- [x] 30. Switch the deploy to the Rust image:
  - the Rust `Dockerfile` replaces the Python one, and `.dockerignore` is updated;
  - in `deploy/remote.sh`: the migrate step becomes `inventory migrate`, the health probe becomes
    `inventory healthcheck`, and uploads are mounted at `/app/data/uploads`. The server-side directories do not
    change;
  - in `deploy/setup_server.sh`: the `set-admin` hint, and a `secret_key.txt` generation that needs no Python
    (`openssl rand -hex 32`);
  - in the `Makefile`: `test` runs `cargo test`.

  Then do one deploy to **staging** (`make deploy ENV=staging`) against a copy of the production database, and
  check the following before production:
  - `/health` answers;
  - Discord login works;
  - sign-up and password login work;
  - existing photos display;
  - a sticker PDF opens.
- [x] 31. Rewrite `README.md` and `CLAUDE.md` for the Rust project: commands, architecture, database, deploy.
  Remove `MIGRATION_PLAN.md`, or keep it as a record (your call at that point)

  *Phase 6 done 2026-10-02, in commits of its own (removal `5953f4c`, move `10dbdd9` + `1814889`, deploy
  `b689a7e`, docs). Departures from the steps above:*
  - *Photos stay mounted at `/app/inventory/api/static/uploads` (the Rust image sets `UPLOADS_DIR` to it) instead
    of moving to `/app/data/uploads`, and the health probe falls back to python: `remote.sh` drives rollbacks too,
    and both keep `make rollback` to the last Python release working. Locally, photos default to `data/uploads`.*
  - *`rust/parity/` went with the Python app it compared against; its result is recorded under Phase 4.*
  - *The image was built and smoke-tested locally the way `remote.sh` runs it — chown, `inventory migrate` on a
    copy of the real database (baselined, backed up, 0001 → 0003), start, health probe, pages, photos, sign-up —
    and Docker reported it healthy. **The staging deploy (`make deploy ENV=staging`) is not done**: it acts on the
    server and waits for your go-ahead.*
  - *This file is kept as the record of the port (the README points to it).*

## 8. Verification summary

- Each step: `cargo build`, `cargo clippy -- -D warnings`, `cargo test` (temp-file SQLite, migrated with sqlx).
- Schema: the sqlx-built schema equals the Alembic-built one. The production DB copy is baselined, not altered,
  apart from the `_sqlx_migrations` table being added.
- Behaviour: the Rust ports of all 69 Python test cases pass, and `pytest` still passes against the untouched
  Python app.
- End to end: `run_parity.py` shows zero differences outside §6.3 (Phase 4, while Python still exists).
- Password login: `tests/password_auth.rs`, plus a manual sign-up and login on staging.
- After the removal: `cargo build`, `cargo clippy -- -D warnings` and `cargo test` pass from the repo root.
  `git grep -i -e python -e flask -e alembic` only finds history notes in the docs. The staging deploy is healthy.
