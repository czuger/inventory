# 📦 Inventory Manager — Les Grognards d'Alsace

A web-based inventory management system built with Flask for **Les Grognards d'Alsace**, a passionate wargaming club
based in Lingolsheim (67380), France, specializing in historical and fantasy miniature strategy games.

---

## 📖 About the Club

**Les Grognards d'Alsace** is a local association of enthusiasts dedicated to miniature strategy gaming — from ancient
historical battles to epic fantasy conflicts. The club manages a shared collection of miniatures, rulebooks, terrain
pieces, paints, and gaming accessories that members can track and use.

This tool was created to help the club keep a clear and organized overview of its ever-growing inventory.

---

## ✨ Features

- **Inventory Tracking** — Add, edit, and remove items from the club's collection
- **Category Management** — Organize items by type *(miniatures, terrain, rulebooks, paints, accessories, etc.)*
- **Stock Status** — Mark items as `available`, `in use`, or `damaged`
- **Item Details** — Store descriptions, quantities, condition notes, and acquisition dates

---

## 🧰 Tech Stack

- **Flask** with server-rendered Jinja templates and Bootstrap 5
- **SQLite** through **SQLAlchemy** (Flask-SQLAlchemy), with **Alembic** for schema migrations
- **Discord OAuth** for login, French/English interface
- **reportlab** for the PDF stickers (with QR codes) and inventory lists

Until October 2026 the data lived in MongoDB. See [Migrating the old MongoDB data](#-migrating-the-old-mongodb-data).

---

## 🚀 Getting Started

```bash
pip install -r requirements.txt
```

Two files are needed at the project root. Neither is versioned.

- `config.json`, with the Discord application's credentials:
  ```json
  { "discord": { "client_id": "...", "client_secret": "..." } }
  ```
- `secret_key.txt`, the Flask session key. Without it, everyone is logged out whenever the app restarts.
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))" > secret_key.txt
  ```

Then create the database and start the development server:

```bash
alembic upgrade head          # creates data/inventory.sqlite3
python -m inventory.api.app
```

To fill an empty database with the club's reference inventory, run `python misc/seed_grognards.py`. **This
wipes all items first**, but keeps the users.

Admin rights are granted from the command line. The user must have logged in through Discord at least once:

```bash
python misc/set_admin.py <discord_username>            # grant
python misc/set_admin.py <discord_username> --revoke   # revoke
```

Run the tests with `pytest`. They need no database server: they build their own SQLite file,
`data/inventory_test.sqlite3`, from the migrations.

---

## 🗄️ Database

The database is a single SQLite file, `data/inventory.sqlite3`. To use another file, set `DATABASE_URL`, for
example `DATABASE_URL=sqlite:////path/to/file.sqlite3`. It runs in WAL mode, so two companion files,
`inventory.sqlite3-wal` and `inventory.sqlite3-shm`, live next to it. **Copy or back up the three files together**,
or better, use `sqlite3 data/inventory.sqlite3 ".backup copy.sqlite3"`.

The schema is managed by Alembic. After changing a model:

```bash
alembic revision --autogenerate -m "describe the change"   # then read the generated file
alembic upgrade head
```

The test suite fails if a model and the migrations disagree. In production, `make deploy` applies pending
migrations by itself, after backing the database up.

---

## 🔄 Migrating the old MongoDB data

The import is done once, with `misc/migrate_mongo_to_sqlite.py`. It reads MongoDB and writes everything into a
SQLite database:

- **New ids.** Every document gets a new integer id, numbered in creation order, and every reference between
  documents is translated to the new ids.
- **Old stickers keep working.** The old id (ObjectId) of every item is kept in the `legacy_object_ids` table.
  The QR codes of stickers printed before the migration point to `/<club>/<items>/<ObjectId>`, and the app
  redirects those links to the item's new address.
- **Photos follow their item.** They are stored in `uploads/<category>/<ObjectId>/`, and are renamed to
  `uploads/<category>/<new id>/` when `--uploads-dir` is given.
- **Nothing is changed in MongoDB.** It remains a complete copy of the old data.

### Options

| Option | Effect |
|---|---|
| `--dry-run` | Does the whole import, prints the report, then **undoes it**. Photos are not renamed; the report says how many would be. |
| `--sqlite PATH` | The SQLite file to write. Defaults to the app's database (`DATABASE_URL`, else `data/inventory.sqlite3`). |
| `--mongo-db NAME` | The MongoDB database to read. Defaults to `mongo.database` in `config.json`. |
| `--uploads-dir DIR` | Also renames the photo folders under `DIR`, once the import has been saved. |
| `--skip-orphans` | Leaves out items whose club (association) no longer exists, and lists them. |

### What the script checks

- **The target must be empty.** The script first brings the database to the latest schema (`alembic upgrade
  head`), then refuses to run if any table already holds data. It never merges.
- **Any inconsistency stops everything.** A missing required field, or a reference to a document that no longer
  exists, is listed in the report and **nothing is written**; the script exits with status 1.
- **Some old data is dropped on purpose.** Borrowing records and duplicate links that point to deleted items are
  skipped and counted. They were already invisible in the app.
- **Leftovers are reported.** The report lists any MongoDB collection it did not import, and any field the new
  schema has no place for.

The current production data needs `--skip-orphans`. Two books point to a club that no longer exists, left over
from an old run of the seed script, which never deleted books. The app could never show them. Everything else
imports cleanly.

### Migrating a local copy

Install the MongoDB driver, which the app no longer needs. Make sure `config.json` still has its `mongo` section
(`server`, `user`, `pass`, `database`), then:

```bash
pip install 'pymongo~=4.16'

# 1. Rehearse: full import, report, nothing kept.
python misc/migrate_mongo_to_sqlite.py --skip-orphans --dry-run

# 2. For real, renaming the local photo folders too.
python misc/migrate_mongo_to_sqlite.py --skip-orphans --uploads-dir inventory/api/static/uploads
```

### Migrating the production server

On the server, the photos belong to the container's user, and MongoDB is only reachable from Docker's
`mongo-network`. So the import runs inside a throwaway container of the new image, which has everything except
the MongoDB driver.

The values below are the defaults from `deploy/config.sh`. Adapt them if you changed them there.

1. **Deploy the new version.** It starts on an empty database: the site shows "No association found." until the
   import is done. The MongoDB data is not touched.
   ```bash
   make deploy
   ```

2. **On the server**, prepare the import. `make deploy` already joins `mongo-network`, and the server's
   `config.json` already holds the right `mongo.server` for it.
   ```bash
   # from your laptop
   scp misc/migrate_mongo_to_sqlite.py ced@nuc150:/home/ced/python/inventory/

   # then on the server
   cd /home/ced/python/inventory
   VERSION=$(cat current_version.txt)
   mongo_import() {
     docker run --rm --user 0 --network mongo-network \
       -v "$PWD/config/config.json:/app/config.json:ro" \
       -v "$PWD/data/db:/app/data" \
       -v "$PWD/data/uploads:/app/inventory/api/static/uploads" \
       -v "$PWD/migrate_mongo_to_sqlite.py:/app/misc/migrate_mongo_to_sqlite.py:ro" \
       "inventory:$VERSION" sh -c "
         pip install -q --root-user-action=ignore 'pymongo~=4.16' &&
         python misc/migrate_mongo_to_sqlite.py --skip-orphans \
           --uploads-dir inventory/api/static/uploads $* &&
         chown -R 10001:10001 /app/data /app/inventory/api/static/uploads"
   }
   ```
   The container runs as root so that it can rename the photo folders. The final `chown` hands the database and
   the photos back to the app's user (uid 10001).

3. **Rehearse.** Read the report: the counts, what was skipped, and any problem.
   ```bash
   mongo_import --dry-run
   ```

4. **Stop the app, import, restart it.** Stopping the app means nobody can create an item in the meantime,
   which would make the database non-empty and the import refuse to run.
   ```bash
   docker stop app-inventory
   mongo_import
   docker start app-inventory
   rm migrate_mongo_to_sqlite.py
   ```

5. **Check:**
   - the lists show the items, with their photos;
   - borrowing histories and suspected duplicates are there;
   - scanning an **old sticker** opens the right item.
   Users have to log in again, because their sessions referred to the old ids.

### If something goes wrong

- **Before step 4:** nothing has changed. A dry run writes nothing, and a failed import writes nothing.
- **To start the import over:** stop the app, delete the database files (`rm data/db/inventory.sqlite3
  data/db/inventory.sqlite3-wal data/db/inventory.sqlite3-shm`), and run step 4 again. As long as MongoDB has not
  changed, items get the same ids again. The photo folders were renamed the first time, so they already match.
- **To go back to MongoDB entirely:** run `make rollback`. The previous release still reads MongoDB, whose data
  was never modified. Anything entered since the migration exists only in SQLite.

Once you no longer need to go back: set `MONGO_NETWORK=''` in `deploy/config.sh`, remove the `mongo` section from
the server's `config.json`, and retire the MongoDB container. Keep the `legacy_object_ids` table as long as old
stickers are on the shelves.

---

## 🚢 Deployment

`make setup` once, then `make deploy` for each release. `make rollback` goes back to the previous release, and
`make status` / `make logs` show what is running. Every setting is in `deploy/config.sh`.

The SQLite database (`data/db/`) and the photos (`data/uploads/`) live on the server, outside the image.
**Before** starting a new version, each deploy applies its migrations, taking a backup in `data/db/backups/` first
when there is something to apply. A rollback never undoes a migration.
