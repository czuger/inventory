import json
import logging
import os
import secrets
from dataclasses import dataclass

from flask import Flask

from inventory.db.base import db


@dataclass
class AppContext:
    app: Flask
    secret_key: str
    config: dict


ROOT_MARKERS = {'requirements.txt', '.git', 'README.md'}
logger = logging.getLogger(__name__)


def find_project_root() -> str:
    """Find project root by traversing up until a root marker is found.

    Root markers: requirements.txt, .git, README.md

    Returns:
        str: Absolute path to project root.

    Raises:
        FileNotFoundError: If project root cannot be found.
    """
    current = os.path.dirname(os.path.abspath(__file__))

    while current != os.path.dirname(current):
        if any(os.path.exists(os.path.join(current, marker)) for marker in ROOT_MARKERS):
            return current
        current = os.path.dirname(current)

    raise FileNotFoundError("Project root not found")


def load_config() -> dict:
    """Load configuration from config.json at project root.

    Returns:
        dict: Configuration data.
    """
    root_dir = find_project_root()
    config_path = os.path.join(root_dir, 'config.json')

    with open(config_path, 'r') as config_file:
        return json.load(config_file)


def load_secret_key() -> str:
    """Load secret key from secret_key.txt at project root.

    Logs an error if secret_key.txt does not exist and returns a random
    secret key instead.

    Returns:
        str: Secret key.
    """
    root_dir = find_project_root()
    secret_key_path = os.path.join(root_dir, 'secret_key.txt')

    try:
        with open(secret_key_path, 'r') as secret_key_file:
            logger.info("Secret key found")
            return secret_key_file.read().strip()

    except FileNotFoundError:
        logger.error("secret_key.txt not found at %s, using random secret key", secret_key_path)
        return secrets.token_hex(32)


def database_url(test: bool = False) -> str:
    """The SQLAlchemy URL of the database, shared by the app, Alembic and the scripts.

    `DATABASE_URL` wins when set, except under `test`, which must never be pointed
    at real data by a stray environment variable. Otherwise it is a SQLite file in
    <project root>/data/ — /app/data/ in the container, where deploy/remote.sh
    mounts the server's data/db/ directory. The directory, not the file: WAL keeps
    two companion files (-wal, -shm) next to the database.

    Args:
        test: If True, use the test database instead.

    Returns:
        str: A SQLAlchemy database URL.
    """
    if not test and os.environ.get('DATABASE_URL'):
        return os.environ['DATABASE_URL']
    data_dir = os.path.join(find_project_root(), 'data')
    os.makedirs(data_dir, exist_ok=True)
    return 'sqlite:///' + os.path.join(data_dir, 'inventory_test.sqlite3' if test else 'inventory.sqlite3')


def initialize(app: Flask = None, test: bool = False) -> AppContext:
    """Initialize the application configuration.

    Loads config from config.json and binds the SQLAlchemy extension to the app.
    The schema itself is Alembic's job (`alembic upgrade head`), not this one's.

    Args:
        app: The Flask application instance to configure.
        test: If True, uses the test database.

    Returns:
        AppContext: A dataclass containing the configured Flask app, its secret
                    key and the configuration dictionary.
    """
    config = load_config()

    app.config['SQLALCHEMY_DATABASE_URI'] = database_url(test)
    db.init_app(app)

    secret_key = load_secret_key()

    return AppContext(app=app, config=config, secret_key=secret_key)
