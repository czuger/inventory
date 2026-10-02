# 📦 Inventory Manager — Les Grognards d'Alsace

A web-based inventory for **Les Grognards d'Alsace**, a passionate wargaming club based in Lingolsheim (67380),
France, specializing in historical and fantasy miniature strategy games.

---

## 📖 About the Club

**Les Grognards d'Alsace** is a local association of enthusiasts dedicated to miniature strategy gaming — from ancient
historical battles to epic fantasy conflicts. The club manages a shared collection of miniatures, rulebooks, terrain
pieces, paints, and gaming accessories that members can track and use.

This tool was created to help the club keep a clear and organized overview of its ever-growing inventory.

---

## ✨ Features

- **Eight kinds of items**: miniatures, terrain, tablecloths, rulebooks, board games, books, equipment and
  consumables, each with its own fields, a location and photos
- **Borrowing**: members borrow and return items; each item keeps its history
- **Suspected duplicates**: link two items that may be the same, across kinds
- **Printing**: sticker sheets with a QR code to each item's page, and inventory lists, as PDFs
- **Accounts**: log in with Discord, or sign up with a username and password
- **French and English**, and several clubs (associations) on one site, each under its own URL

---

## 🧰 Tech Stack

- **Rust**: [axum](https://github.com/tokio-rs/axum) on tokio, server-rendered
  [minijinja](https://github.com/mitsuhiko/minijinja) templates with Bootstrap 5
- **SQLite** through [sqlx](https://github.com/launchbadge/sqlx), with sqlx migrations
- **Discord OAuth** and argon2id passwords for login
- PDFs written directly (stickers with QR codes, inventory lists)

The app was a Flask application until October 2026; `MIGRATION_PLAN.md` records how it was ported and what changed.
Before that, until October 2026 too, the data lived in MongoDB.

---

## 🚀 Getting Started

You need a Rust toolchain ([rustup](https://rustup.rs)). Two files are needed at the project root. Neither is
versioned.

- `config.json`, with the Discord application's credentials:
  ```json
  { "discord": { "client_id": "...", "client_secret": "..." } }
  ```
- `secret_key.txt`, the key sessions are signed with. Without it, everyone is logged out whenever the app restarts.
  ```bash
  openssl rand -hex 32 > secret_key.txt
  ```

Then create the database and start the server (on <http://localhost:8000>):

```bash
cargo run -- migrate          # creates data/inventory.sqlite3
cargo run                     # same as `cargo run -- serve`
```

Admin rights are granted from the command line, to a user who has logged in (or signed up) at least once. A Discord
member can also be given a password, to log in either way:

```bash
cargo run -- set-admin <username>             # grant
cargo run -- set-admin <username> --revoke    # revoke
cargo run -- set-password <username>          # prompts for the password twice
```

Run the tests with `make test` (`cargo test`, then clippy). They need nothing else: each test builds its own SQLite
file from the migrations, and Discord is mocked.

### Settings

Everything else comes from the environment (a `.env` file at the root is read too):

| Variable           | Default                          | Meaning                                                   |
|--------------------|----------------------------------|-----------------------------------------------------------|
| `DATABASE_URL`     | `sqlite:data/inventory.sqlite3`  | The database file (`sqlite:///abs/path` works too)        |
| `UPLOADS_DIR`      | `data/uploads`                   | Where item photos are stored                              |
| `BIND_ADDR`        | `0.0.0.0:8000`                   | Address the server listens on                             |
| `URL_PREFIX`       | none                             | Sub-path the site is served under (links and cookie only) |
| `INVENTORY_ROOT`   | found by walking up to `Cargo.toml`, `.git` or `README.md` | Where `config.json`, `secret_key.txt` and `data/` are |
| `DISCORD_API_BASE` | `https://discord.com/api`        | Discord's API (the tests point it at a mock)              |
| `RUST_LOG`         | `info`                           | Log level                                                 |

---

## 🗄️ Database

The database is a single SQLite file, `data/inventory.sqlite3` by default. It runs in WAL mode, so two companion files,
`inventory.sqlite3-wal` and `inventory.sqlite3-shm`, live next to it. **Copy or back up the three files together**, or
better, use `sqlite3 data/inventory.sqlite3 ".backup copy.sqlite3"`.

The schema is in `migrations/`, applied by `inventory migrate`, which backs the database up into `backups/` (next to
it) before applying anything to a database that already has data. To change the schema, add the next numbered file
(`migrations/0004_what_changes.sql`); never edit one that has been applied: `migrate` refuses a migration whose
checksum changed. A table SQLite cannot alter is rebuilt (create, copy, drop, rename — see `0002`); migrations run
with foreign keys off and are checked for dangling references before they commit.

SQL queries are checked at compile time against the data in `.sqlx/`, so a build needs no database. After adding or
changing a query, regenerate it with `scripts/sqlx-prepare.sh` and commit the result.

`legacy_object_ids` maps the MongoDB id of every item imported in 2026 to its current id: stickers printed before that
encode the old id in their QR code, and the app redirects them. Keep that table while such stickers are around.

---

## 🚢 Deployment

`make setup` once, then `make deploy` for each release. `make rollback` goes back to the previous release, and
`make status` / `make logs` show what is running. Every setting is in `deploy/config.sh`.

| Command         | What it does                                                                               |
|-----------------|--------------------------------------------------------------------------------------------|
| `make help`     | List the commands                                                                          |
| `make setup`    | One-time server preparation: directories, Docker check, nginx snippet                      |
| `make deploy`   | Build the image for the server's architecture, ship it, migrate, restart, health check     |
| `make rollback` | Switch back to the previously deployed version (nothing is rebuilt or transferred)         |
| `make status`   | Running container, current/previous versions, networks and `/health`, as seen from the server |
| `make logs`     | Follow the container logs (Ctrl-C to stop)                                                 |
| `make versions` | List the versions kept on the server                                                       |
| `make nginx`    | Re-install the nginx snippet only (after changing `URL_PREFIX`)                            |
| `make test`     | Run the test suite and clippy locally                                                      |

Options are passed as `NAME=value` after the command (`make deploy ENV=staging`); all but `ENV` can also come
from the environment (`SSH_HOST=ced@other-box make deploy`). The defaults live in `deploy/config.sh`:

| Option            | Default                                        | Meaning                                                   |
|-------------------|------------------------------------------------|-----------------------------------------------------------|
| `ENV`             | `production`                                   | Which instance to act on: `production` or `staging`       |
| `SSH_HOST`        | `ced@nuc150`                                   | Server to deploy to                                       |
| `REMOTE_DIR`      | `/home/ced/python/inventory`                   | Its directory on the server (releases, config, data)      |
| `CONTAINER_NAME`  | `app-inventory`                                | Container name, which nginx proxies to                    |
| `IMAGE_NAME`      | `inventory`                                    | Image name; the version is the tag                        |
| `URL_PREFIX`      | `/inventory`                                   | Sub-path the site is served under (nginx + app links)     |
| `TARGET_PLATFORM` | `linux/amd64`                                  | Server architecture the image is built for                |
| `KEEP_RELEASES`   | `3`                                            | Releases kept on the server                               |
| `MONGO_NETWORK`   | `mongo-network`                                | Extra network joined for pre-SQLite rollbacks; `''` for none |
| `DOCKER_NETWORK`  | `nginx-common-network`                         | nginx's shared docker network                             |
| `NGINX_CONTAINER` | `nginx-proxy`                                  | The nginx container restarted by `setup` / `nginx`        |
| `NGINX_CONF_DIR`  | `/home/ced/services/nginx_proxy/sites/apps`    | Where the nginx snippet is installed                      |
| `NGINX_CONF_NAME` | `inventory.conf`                               | The snippet's file name                                   |
| `APP_PORT`        | `8000`                                         | The app's port inside the container (not published)       |

With `ENV=staging`, `REMOTE_DIR`, `CONTAINER_NAME`, `IMAGE_NAME`, `URL_PREFIX` and `NGINX_CONF_NAME` default to
their `inventory_staging` counterparts, and `MONGO_NETWORK` to none.

Every command also takes `ENV=staging` (`make setup ENV=staging`, `make deploy ENV=staging`, …) to act on a
separate staging instance instead: its own directory next to production's (`/home/ced/python/inventory_staging`),
with its own `config/`, database and photos, its own container and image, served under `/inventory_staging`. It
never reads or writes anything of production's. Its database starts empty, and its Discord redirect URI
(`https://apps.ieroe.com/inventory_staging/auth/discord/callback`) has to be added to the Discord application.

The SQLite database (`data/db/`) and the photos (`data/uploads/`) live on the server, outside the image.
**Before** starting a new version, each deploy applies its migrations, taking a backup in `data/db/backups/` first
when there is something to apply. A rollback never undoes a migration.

On the server, admin rights and passwords are set inside the running container:

```bash
ssh ced@nuc150 "docker exec app-inventory inventory set-admin <username>"
ssh -t ced@nuc150 "docker exec -it app-inventory inventory set-password <username>"
```

### The first deploy of the Rust version

It needs nothing special: the server's `config/` and `data/` stay as they are, and nobody is logged out (the session
cookies are compatible). Its migrations run before it starts, after a backup:

1. the database Alembic built is recognized and recorded as migration 0001, untouched;
2. `0002` rebuilds `users` for password login, keeping every user and id;
3. `0003` drops Alembic's `alembic_version` table.

`make rollback` to the last Python release still works afterwards: it runs on the new schema (the added columns are
ignored), finds the photos where it expects them, and passes its health check. Accounts made by signing up cannot log
in on it, as it has no password login. To go further back than that, restore the backup the deploy took.

Building for `linux/amd64` on an Apple Silicon Mac compiles under emulation: the first build takes a while, later
ones reuse the dependency layer.
