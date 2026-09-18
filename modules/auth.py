"""
Authentification des utilisateurs.

Vérifie les identifiants saisis contre ceux stockés dans MongoDB, et gère
la session Streamlit (qui est connecté, avec quel rôle).
"""

from typing import Optional

import bcrypt
import streamlit as st

from modules.db_mongo import get_users_collection


def authenticate(username: str, password: str) -> Optional[dict]:
    """
    Vérifie le couple username / password.

    Retourne le document utilisateur (dict) si les identifiants sont
    corrects, sinon None. Ne dit jamais si c'est le username ou le mot de
    passe qui est fautif : message générique, pour ne pas donner 
    d'indice à quelqu'un qui tenterait de deviner un compte.
    """
    users = get_users_collection()
    user = users.find_one({"username": username})

    if user is None:
        return None

    stored_hash = user["password_hash"].encode("utf-8")
    entered_password = password.encode("utf-8")

    if bcrypt.checkpw(entered_password, stored_hash):
        return user

    return None


def login_user(user: dict) -> None:
    """Enregistre l'utilisateur connecté dans la session Streamlit."""
    st.session_state["logged_in"] = True
    st.session_state["username"] = user["username"]
    st.session_state["role"] = user["role"]


def logout_user() -> None:
    """Déconnecte l'utilisateur courant (vide les infos de session)."""
    for key in ("logged_in", "username", "role"):
        st.session_state.pop(key, None)


def is_logged_in() -> bool:
    """True si un utilisateur est actuellement connecté dans cette session."""
    return st.session_state.get("logged_in", False)


def get_current_role() -> Optional[str]:
    """Retourne le rôle de l'utilisateur connecté ("admin"/"user"), ou None."""
    return st.session_state.get("role")


def require_role(expected_role: str) -> None:
    """
    Protège une page : arrête son exécution si l'utilisateur n'est pas
    connecté avec le bon rôle. À appeler tout en haut d'une page protégée.
    """
    if not is_logged_in() or get_current_role() != expected_role:
        st.error("Accès refusé. Veuillez vous connecter avec le compte adéquat.")
        st.stop()