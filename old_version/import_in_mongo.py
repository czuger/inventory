import pandas as pd
import requests
from pymongo import MongoClient

# --- CONFIG ---

SHEET_ID = "ID_DE_TA_FEUILLE"
SHEET_NAME = "Sheet1"

MONGO_URI = "mongodb://nic150:27017/"
DB_NAME = "grognards"
COLLECTION = "inventory"

# --- TELECHARGEMENT DU CSV DE GOOGLE SHEETS ---

url = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/gviz/tq?tqx=out:csv&sheet={SHEET_NAME}"

df = pd.read_csv(url)

# --- CONNEXION MONGODB ---

client = MongoClient(MONGO_URI)
db = client[DB_NAME]
collection = db[COLLECTION]

# --- CONVERSION DES LIGNES ---

documents = []

for _, row in df.iterrows():
    doc = {
        "name": row.get("Matériel"),
        "quantity": row.get("quantité"),
        "notes": row.get("remarques"),
        "location": {
            "placard_1_porte": row.get("placard 1 porte"),
            "placard_2_portes": row.get("placard 2 portes"),
            "piece_1": row.get("pièce 1"),
            "vitrine_1": row.get("vitrine 1"),
            "vitrine_2": row.get("vitrine 2"),
            "piece_2": row.get("pièce 2"),
            "armoire_1": row.get("armoire 1"),
            "armoire_2": row.get("armoire 2")
        }
    }

    documents.append(doc)

# --- INSERTION DANS MONGODB ---

if documents:
    collection.insert_many(documents)

print("Import terminé :", len(documents), "objets ajoutés")
