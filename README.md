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
cargo run -- seed             # optional: loads the club inventory (fresh database only)
cargo run                     # same as `cargo run -- serve`
```

`seed` loads `misc/grognards_seed.json` (built into the binary; `--file` loads another): the club workbook
`misc/20241206_inventaire Grognards.xlsx` read line by line, as the audit in `misc/inventory_xlsx_extraction_report.md`
describes, then mapped to the app's items. Each item names its sheet lines (`source`) and what was interpreted
(`note`). That JSON file is now the reference, so edit it rather than the workbook. Items the sheet does not place are
under `À localiser`; those at a member's home are under `Hors club`; gift candidates and stock for sale are under
`Hors stock`. The command checks the whole file first, writes in one transaction, and refuses a database that already
holds an association or a game.

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
| `SOCKET_PATH`      | none                             | Listen on this Unix socket instead of `BIND_ADDR`         |
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

The app runs on the server as a plain binary under a systemd user unit. nginx runs in a container
(`nginx-proxy`, from the `nginx_proxy` project) and reaches the app through a **Unix socket**: no port is opened.

```
browser ──https──▶ nginx-proxy (container)
                       │ proxy_pass http://unix:/sockets/inventory.sock:/
                       ▼
        /home/ced/services/nginx_proxy/sockets/inventory.sock   (directory mounted :ro)
                       ▲
                       │ listens (SOCKET_PATH)
              systemd user unit inventory (on the host)
```

The socket directory belongs to `nginx_proxy` and is shared with its other apps (wiki_to_text). It must exist,
owned by `ced`, and be mounted in the container — `make setup` and every deploy check it, and say how to fix it:
`mkdir -p /home/ced/services/nginx_proxy/sockets` **before** adding
`- /home/ced/services/nginx_proxy/sockets:/sockets:ro` to the nginx service's volumes and `docker compose up -d`
(a missing directory would be created by docker as root). `:ro` does not stop nginx from connecting; the app creates
its socket as `0666` because nginx's worker runs as another user.

Deploys cross-compile it on your machine with [cargo-zigbuild](https://github.com/rust-cross/cargo-zigbuild), once installed:

```bash
brew install zig && cargo install cargo-zigbuild && rustup target add x86_64-unknown-linux-musl
```

| Command         | What it does                                                                               |
|-----------------|--------------------------------------------------------------------------------------------|
| `make help`     | List the commands                                                                          |
| `make setup`    | One-time server preparation: directories, lingering, socket mount check, nginx snippet     |
| `make deploy`   | Build a static binary for the server, ship it, migrate, restart, health check              |
| `make rollback` | Switch back to the previously deployed version (nothing is rebuilt or transferred)         |
| `make status`   | Versions, the unit's state, `/health` over the socket and whether nginx sees it            |
| `make logs`     | Follow the app's logs (journald; Ctrl-C to stop)                                           |
| `make versions` | List the versions kept on the server                                                       |
| `make nginx`    | Re-install the nginx snippet only (after changing `URL_PREFIX` or the socket)              |
| `make test`     | Run the test suite and clippy locally                                                      |

Options are passed as `NAME=value` after the command (`make deploy ENV=staging`); all but `ENV` can also come
from the environment (`SSH_HOST=ced@other-box make deploy`). The defaults live in `deploy/config.sh`:

| Option             | Default                                     | Meaning                                                   |
|--------------------|---------------------------------------------|-----------------------------------------------------------|
| `ENV`              | `production`                                | Which instance to act on: `production` or `staging`       |
| `SSH_HOST`         | `ced@nuc150`                                | Server to deploy to                                       |
| `REMOTE_DIR`       | `/home/ced/rust/inventory`                | Its directory on the server (releases, config, data)      |
| `SERVICE_NAME`     | `inventory`                                 | The systemd user unit running the app                     |
| `SOCKET_DIR`       | `/home/ced/services/nginx_proxy/sockets`    | Directory of the app's socket, on the host                |
| `NGINX_SOCKET_DIR` | `/sockets`                                  | The same directory inside the nginx container             |
| `SOCKET_NAME`      | `inventory.sock`                            | The socket's file name                                    |
| `NGINX_CONTAINER`  | `nginx-proxy`                               | The nginx container (`nginx -t`, reload, mount check)     |
| `URL_PREFIX`       | `/inventory`                                | Sub-path the site is served under (nginx + app links)     |
| `TARGET`           | `x86_64-unknown-linux-musl`                 | Server target the binary is built for                     |
| `KEEP_RELEASES`    | `3`                                         | Releases kept on the server                               |
| `NGINX_CONF_DIR`   | `/home/ced/services/nginx_proxy/sites/apps` | Where the nginx snippet is installed                      |
| `NGINX_CONF_NAME`  | `inventory.conf`                            | The snippet's file name                                   |

With `ENV=staging`, `REMOTE_DIR`, `SERVICE_NAME`, `URL_PREFIX`, `SOCKET_NAME` and `NGINX_CONF_NAME` default to
their `inventory_staging` counterparts.

Every command also takes `ENV=staging` (`make setup ENV=staging`, `make deploy ENV=staging`, …) to act on a
separate staging instance instead: its own directory next to production's (`/home/ced/rust/inventory_staging`),
with its own `config/`, database and photos, its own unit and socket, served under `/inventory_staging`. It
never reads or writes anything of production's. Its database starts empty, and its Discord redirect URI
(`https://apps.ieroe.com/inventory_staging/auth/discord/callback`) has to be added to the Discord application.

On the server, each instance's directory holds `releases/` (the binaries, `current` pointing at the running one),
`config/` (`config.json`, `secret_key.txt`), `data/db/` (the SQLite database) and `data/uploads/` (the photos).
**Before** starting a new version, each deploy applies its migrations, taking a backup in `data/db/backups/` first
when there is something to apply. A rollback never undoes a migration.

Admin rights and passwords are set with the `run` wrapper, which runs the current binary on the server's database:

```bash
ssh ced@nuc150 "/home/ced/rust/inventory/run set-admin <username>"
ssh -t ced@nuc150 "/home/ced/rust/inventory/run set-password <username>"
```

### Moving an instance off Docker

Releases up to October 2026 ran in a container. To switch an instance over, once:

1. on the server, stop the old container: `docker rm -f app-inventory` (`app-inventory_staging` for staging);
2. on the server, move the instance from the Python-era directory to the Rust one (the `current` symlink is
   relative, and the deploy rewrites `app.env`, `run` and the unit with the new paths):
   `mkdir -p /home/ced/rust && mv /home/ced/python/inventory /home/ced/rust/inventory`
   (`inventory_staging` likewise);
3. on the server, give the data back to your user: `sudo chown -R ced: /home/ced/rust/inventory/data`
   (the container ran as uid 10001);
4. `make setup` (checks the socket mount, installs the nginx snippet pointing at the socket, enables lingering);
5. `make deploy`.

The database, photos and config stay where they are and nobody is logged out. There is no rollback to a container
release: to go back further than the first native deploy, restore the backup it took.
