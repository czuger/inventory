import json
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()

def load_config(config_file='config.json'):
    """Charge les configurations depuis un fichier JSON"""
    if not os.path.exists(config_file):
        raise FileNotFoundError(f"Le fichier de configuration '{config_file}' n'existe pas")

    with open(config_file, 'r') as f:
        config = json.load(f)

    return config


def get_db_url(config):
    """Construit l'URL de connexion à partir des configurations"""
    db_config = config.get('database', {})

    username = db_config.get('username')
    password = db_config.get('password')
    host = db_config.get('host', 'localhost')
    port = db_config.get('port', 5432)
    dbname = db_config.get('dbname')

    # Construction de l'URL
    if username and password:
        url = f"postgresql+psycopg://{username}:{password}@{host}:{port}/{dbname}"
    else:
        url = f"postgresql+psycopg://{host}:{port}/{dbname}"

    return url


def init_db(config_file='config.json'):
    """Initialise la base de données à partir du fichier de configuration"""
    config = load_config(config_file)
    db_url = get_db_url(config)

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    return engine


def create_session(engine):
    """Crée une session SQLAlchemy"""
    Session = sessionmaker(bind=engine)
    return Session()