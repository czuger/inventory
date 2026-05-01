# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Inventory management web app for a French wargaming club ("Les Grognards d'Alsace"). Tracks miniatures, terrain, rulebooks, paints, etc.

## Commands

### Run locally
```bash
pip install -r requirements.txt
python -m inventory.api.app
```

### Docker (production-style)
```bash
cd docker/
bash create_network.sh      # one-time: creates external Docker networks
bash set_secret_key.bash    # one-time: generates secret_key.txt
docker compose up -d --build
```

### Deploy to server
```bash
bash deploy.sh              # rsyncs to nuc150 and restarts container via SSH
```

### Data import / category rebuild
```bash
python inventory/import.py <json_file> [--db-url <url>] [--clear]
python inventory/build_categories.py
```

There are no tests and no linter configured.

## Architecture

**Stack:** Flask 3.1.3 · MongoEngine 0.29.3 (MongoDB ORM) · Gunicorn · Jinja2 + Bootstrap 5

**Entry point:** `inventory/api/app.py` — all routes live here. Three routes only: list (`/`), detail (`/item/<id>`), and edit (`/item/<id>/edit`). No create or delete routes yet.

**Initialization:** `inventory/libs/initialization.py` loads `config.json` from the project root (found via ROOT_MARKERS), establishes the MongoEngine connection, and sets up the Flask secret key from `secret_key.txt`.

**Models** (`inventory/libs/item.py`):
- `Item` → collection `inventaire`. Main document with embedded `Localisation`, `Quantite`, `Dimensions`. Images stored as binary inside MongoDB (no filesystem storage).
- `Category` (`inventory/libs/categories.py`) → hierarchical category + subcategory used to filter the list view.

**Config:** `config.json` at repo root (not committed — see `config.json.template` in `old_version/config/`). Structure:
```json
{"mongo": {"server": "...", "user": "...", "pass": "...", "database": "grognards"}}
```

**Docker networking:** The container expects two external Docker networks (`mongo-network` and `app-inventory`) to exist before `docker compose up`. The MongoDB server (`nuc150`) is not containerized here — it's an external host.

**UI language:** French throughout — field names, labels, templates.

## Miscellaneous

- `old_version/` contains the previous MongoDB-import scripts; it is being removed (files staged for deletion).
- `inventory/db/__init__.py` appears to be an alternative/legacy model layer — it is not used by the Flask app.
- Logging is set to DEBUG with pymongo/Werkzeug loggers suppressed in `initialization.py`.
