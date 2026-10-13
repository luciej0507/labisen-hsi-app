"""
Connexion à MongoDB et accès à la collection "users".

Centralise la connexion Mongo pour ne pas la dupliquer dans chaque script/page.
L'URI de connexion est lue depuis les variables d'environnement (.env).
"""

import os
from typing import Optional

from dotenv import load_dotenv
from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

_client: Optional[MongoClient] = None


def get_client() -> MongoClient:
    """Retourne un client Mongo unique partagé par toute l'appli."""
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI)
    return _client


def get_db() -> Database:
    """Retourne la base de données."""
    return get_client()[MONGO_DB_NAME]


def get_users_collection() -> Collection:
    """
    Retourne la collection "users".

    Un index unique sur "username" est créé s'il n'existe pas déjà, pour
    empêcher tout doublon de compte au niveau base de données (et pas
    seulement au niveau applicatif).
    """
    users = get_db()["users"]
    users.create_index([("username", ASCENDING)], unique=True)
    return users