import json
import logging
import os
import secrets
from dataclasses import dataclass

from flask import Flask
from mongoengine import connect


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


def initialize(app: Flask = None, test: bool = False) -> AppContext:
    """Initialize the application configuration.

    Loads config from config.json and sets up Flask, OpenAI, and MongoDB connections.

    Args:
        app: The Flask application instance to configure.
        test: If True, disables OpenAI API key and uses a test database.

    Returns:
        AppContext: A dataclass containing the configured Flask app, Tweepy API,
                    Tweepy Client, and configuration dictionary.
    """
    config = load_config()

    db_name = config['mongo']['database'] + ('_test' if test else '')

    connect(
        db=db_name,
        host=config['mongo']['server'],
        port=27017,
        username=config['mongo']['user'],
        password=config['mongo']['pass'],
        authentication_source='admin',
        uuidRepresentation="standard"
    )

    secret_key = load_secret_key()

    return AppContext(app=app, config=config, secret_key=secret_key)
