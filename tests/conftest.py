"""
tests/conftest.py : fixtures partagées par tous les tests.

Les fixtures de ce fichier sont disponibles automatiquement dans chaque
fichier de test du dossier, sans avoir besoin de les importer.
"""

import mongomock
import pytest


@pytest.fixture
def users():
    """
    Collection "users" factice (en mémoire), vide, avec l'index unique
    sur username, comme en production.
    Chaque test reçoit une collection neuve : les tests sont indépendants.
    """
    collection = mongomock.MongoClient().db.users
    collection.create_index("username", unique=True)
    return collection


@pytest.fixture
def creer_compte(users):
    """
    Fournit une fonction qui insère rapidement un compte dans la fausse base.
    Le mot de passe n'est pas haché (bcrypt est lent) : ces comptes servent
    uniquement à préparer le décor des tests.

    Avec password_hash=None, on crée un compte "en attente" (sans mot de
    passe), comme ceux qui viennent de l'import CSV.
    """

    def _creer(username: str, role: str = "user", password_hash="hash_bidon") -> dict:
        document = {
            "nom": "Nom",
            "prenom": "Prénom",
            "email": None,
            "username": username,
            "password_hash": password_hash,
            "role": role,
            "datasets_access": [],
        }
        resultat = users.insert_one(document)
        # On récupère l'identifiant généré par la base
        document["_id"] = resultat.inserted_id
        return document

    return _creer


@pytest.fixture
def session_state(monkeypatch):
    """
    Remplace st.session_state par un simple dictionnaire, vide au départ.
    Les modules qui font "st.session_state[...]" (auth.py, flash.py)
    utilisent alors ce dictionnaire, sans avoir besoin d'une vraie session
    Streamlit. L'original est remis en place à la fin du test.
    """
    # Import local : Streamlit n'est chargé que pour les tests qui utilisent
    # cette fixture, et pas pour les autres (par exemple ceux des datasets)
    import streamlit as st

    faux_etat = {}
    monkeypatch.setattr(st, "session_state", faux_etat)
    return faux_etat