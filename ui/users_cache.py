"""
ui/users_cache.py : cache Streamlit autour de la logique des comptes.

Partagé par les pages d'administration qui touchent aux comptes
(ajout et gestion), pour ne pas dupliquer la fonction.
"""

import streamlit as st

from modules.db_mongo import get_users_collection
from modules.users import ensure_username_index


@st.cache_resource
def ensure_username_index_once() -> bool:
    """
    Enveloppe Streamlit autour de ensure_username_index (modules/users.py),
    pour que l'index ne soit créé qu'une seule fois par processus.
    """
    return ensure_username_index(get_users_collection())