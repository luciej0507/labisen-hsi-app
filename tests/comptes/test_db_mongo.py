"""
tests/comptes/test_db_mongo.py : tests de modules/db_mongo.py.

Seule la création de l'index sur "username" est testée ici. Aucune connexion
réelle n'est ouverte : on utilise une fausse collection mongomock.
"""

import mongomock
import pytest
from pymongo.errors import PyMongoError

from modules import db_mongo


@pytest.fixture(autouse=True)
def tentative_remise_a_zero(monkeypatch):
    """
    Remet à False le drapeau "index déjà tenté" avant chaque test.
    Sans cela, seul le premier test de la session créerait l'index.
    monkeypatch remet la valeur d'origine à la fin du test.
    """
    monkeypatch.setattr(db_mongo, "_index_username_tente", False)


class CollectionEnPanne:
    """Fausse collection dont create_index échoue toujours."""

    def __init__(self):
        # Compte le nombre de tentatives de création d'index
        self.appels = 0

    def create_index(self, *args, **kwargs):
        self.appels += 1
        raise PyMongoError("échec simulé")


def test_creer_index_username_cree_un_index_unique():
    """Sur une collection neuve, l'index unique sur username est créé."""
    collection = mongomock.MongoClient().db.users

    db_mongo._creer_index_username(collection)

    index = collection.index_information()
    assert "username_1" in index
    assert index["username_1"]["unique"] is True


def test_creer_index_username_echec_est_ignore():
    """Si MongoDB refuse l'index, l'erreur est ignorée (pas d'exception)."""
    collection = CollectionEnPanne()

    db_mongo._creer_index_username(collection)

    assert collection.appels == 1


def test_creer_index_username_une_seule_tentative():
    """Une fois tentée, la création n'est pas refaite aux appels suivants."""
    collection = CollectionEnPanne()

    db_mongo._creer_index_username(collection)
    db_mongo._creer_index_username(collection)

    assert collection.appels == 1