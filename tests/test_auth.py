"""
tests/test_auth.py : tests de modules/auth.py.

Deux éléments sont remplacés pendant les tests (avec monkeypatch) :
- get_users_collection : renvoie la fausse collection mongomock au lieu de
  se connecter à la vraie base MongoDB
- st.session_state : simple dictionnaire (fixture session_state du conftest)
"""

import bcrypt
import pytest
import streamlit as st

from modules import auth


@pytest.fixture
def comptes(users, monkeypatch):
    """
    Prépare la fausse base avec deux comptes :
    - alice (rôle user, mot de passe "secret123")
    - admin1 (rôle admin, mot de passe "adminpass")
    et branche auth.py dessus.
    """
    # rounds=4 est le minimum de bcrypt : le hachage est quasi instantané
    for username, role, mot_de_passe in [
        ("alice", "user", "secret123"),
        ("admin1", "admin", "adminpass"),
    ]:
        hash_mdp = bcrypt.hashpw(mot_de_passe.encode("utf-8"), bcrypt.gensalt(rounds=4))
        users.insert_one(
            {
                "username": username,
                "password_hash": hash_mdp.decode("utf-8"),
                "role": role,
            }
        )

    # auth.py appellera cette fonction au lieu de la vraie
    monkeypatch.setattr(auth, "get_users_collection", lambda: users)
    return users


# ---------------------------------------------------------------------------
# authenticate
# ---------------------------------------------------------------------------

def test_authenticate_bons_identifiants(comptes):
    """Les bons identifiants renvoient le document de l'utilisateur."""
    user = auth.authenticate("alice", "secret123")

    assert user is not None
    assert user["username"] == "alice"
    assert user["role"] == "user"


def test_authenticate_mauvais_mot_de_passe(comptes):
    """Un mauvais mot de passe renvoie None."""
    assert auth.authenticate("alice", "mauvais") is None


def test_authenticate_mot_de_passe_vide(comptes):
    """Un mot de passe vide renvoie None."""
    assert auth.authenticate("alice", "") is None


def test_authenticate_utilisateur_inconnu(comptes):
    """Un username qui n'existe pas renvoie None."""
    assert auth.authenticate("inconnu", "secret123") is None


def test_authenticate_username_sensible_a_la_casse(comptes):
    """Le username est sensible à la casse : "Alice" n'est pas "alice"."""
    assert auth.authenticate("Alice", "secret123") is None


# ---------------------------------------------------------------------------
# authenticate_with_role
# ---------------------------------------------------------------------------

def test_authenticate_with_role_bon_role(comptes):
    """Identifiants corrects et rôle attendu : le compte est renvoyé."""
    user = auth.authenticate_with_role("admin1", "adminpass", "admin")

    assert user is not None
    assert user["username"] == "admin1"


def test_authenticate_with_role_mauvais_role(comptes):
    """Identifiants corrects mais rôle différent : refusé."""
    assert auth.authenticate_with_role("alice", "secret123", "admin") is None
    assert auth.authenticate_with_role("admin1", "adminpass", "user") is None


def test_authenticate_with_role_mauvais_mot_de_passe(comptes):
    """Bon rôle mais mauvais mot de passe : refusé."""
    assert auth.authenticate_with_role("admin1", "mauvais", "admin") is None


# ---------------------------------------------------------------------------
# login_user, logout_user, is_logged_in, get_current_role
# ---------------------------------------------------------------------------

def test_etat_initial_non_connecte(session_state):
    """Sans connexion, personne n'est connecté et il n'y a pas de rôle."""
    assert auth.is_logged_in() is False
    assert auth.get_current_role() is None


def test_login_user_enregistre_la_session(session_state):
    """login_user remplit la session avec le username et le rôle."""
    auth.login_user({"username": "alice", "role": "user"})

    assert session_state["logged_in"] is True
    assert session_state["username"] == "alice"
    assert session_state["role"] == "user"
    assert auth.is_logged_in() is True
    assert auth.get_current_role() == "user"


def test_logout_user_vide_la_session(session_state):
    """logout_user retire les infos de connexion, mais pas le reste."""
    auth.login_user({"username": "alice", "role": "user"})
    session_state["autre_donnee"] = "a conserver"

    auth.logout_user()

    assert auth.is_logged_in() is False
    assert auth.get_current_role() is None
    assert "username" not in session_state
    # Les données sans rapport avec la connexion ne sont pas touchées
    assert session_state["autre_donnee"] == "a conserver"


def test_logout_user_sans_etre_connecte(session_state):
    """Se déconnecter quand on ne l'est pas ne provoque pas d'erreur."""
    auth.logout_user()

    assert auth.is_logged_in() is False


# ---------------------------------------------------------------------------
# require_role
# ---------------------------------------------------------------------------

class ArretPage(Exception):
    """Simule st.stop(), qui interrompt l'exécution de la page."""


@pytest.fixture
def messages_erreur(monkeypatch):
    """
    Remplace st.error et st.stop par des espions :
    - st.error range son message dans la liste renvoyée
    - st.stop lève ArretPage, comme le vrai qui arrête le script
    """
    messages = []

    def faux_stop():
        raise ArretPage()

    monkeypatch.setattr(st, "error", messages.append)
    monkeypatch.setattr(st, "stop", faux_stop)
    return messages


def test_require_role_non_connecte(session_state, messages_erreur):
    """Sans connexion, l'accès est refusé et la page s'arrête."""
    with pytest.raises(ArretPage):
        auth.require_role("admin")

    assert len(messages_erreur) == 1
    assert "refusé" in messages_erreur[0]


def test_require_role_mauvais_role(session_state, messages_erreur):
    """Un utilisateur connecté avec un autre rôle est refusé."""
    auth.login_user({"username": "alice", "role": "user"})

    with pytest.raises(ArretPage):
        auth.require_role("admin")

    assert len(messages_erreur) == 1


def test_require_role_bon_role(session_state, messages_erreur):
    """Avec le bon rôle, la page continue : ni erreur ni arrêt."""
    auth.login_user({"username": "admin1", "role": "admin"})

    auth.require_role("admin")

    assert messages_erreur == []