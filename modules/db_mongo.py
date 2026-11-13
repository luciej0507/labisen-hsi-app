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
from pymongo.errors import PyMongoError

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME")

_client: Optional[MongoClient] = None

# Vrai une fois la création de l'index sur "username" tentée dans ce
# processus : elle n'est faite qu'une seule fois, pas à chaque appel.
_index_username_tente = False


def get_client() -> MongoClient:
    """Retourne un client Mongo unique partagé par toute l'appli."""
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI)
    return _client


def get_db() -> Database:
    """Retourne la base de données."""
    return get_client()[MONGO_DB_NAME]


def _creer_index_username(users: Collection) -> None:
    """
    Crée un index unique sur "username" (une seule tentative par processus).

    L'index empêche tout doublon de compte au niveau base de données (et pas
    seulement au niveau applicatif), même en cas de clics simultanés.

    Si l'index ne peut pas être créé (par exemple parce que des doublons
    existent déjà en base), l'erreur est ignorée : l'application continue de
    fonctionner avec ses vérifications habituelles.
    """
    global _index_username_tente
    if _index_username_tente:
        return
    # On marque la tentative avant, pour ne pas réessayer à chaque appel
    # si elle échoue
    _index_username_tente = True
    try:
        users.create_index([("username", ASCENDING)], unique=True)
    except PyMongoError:
        pass


def get_users_collection() -> Collection:
    """
    Retourne la collection "users".

    Au premier appel du processus, un index unique sur "username" est créé
    s'il n'existe pas déjà (voir _creer_index_username).
    """
    users = get_db()["users"]
    _creer_index_username(users)
    return users
