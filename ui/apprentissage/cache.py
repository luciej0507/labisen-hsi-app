"""Lectures mises en cache de la page Apprentissage.

Elles évitent de relire le serveur à chaque clic. Les autres fichiers
importent ces fonctions : chacune n'est définie qu'une seule fois, ce qui
permet aussi de vider son cache avec `.clear()`.
"""

import streamlit as st

from modules.apprentissage.etape_dataset import lister_datasets_complets
from modules.apprentissage.etape_patching import (
    lire_dimensions_dataset,
    lire_versions,
)
from modules.datasets.stats import calculer_stats
from modules.db_mongo import get_users_collection

# Durée (en secondes) pendant laquelle les lectures sur le serveur sont gardées
DUREE_CACHE = 60


@st.cache_data(ttl=DUREE_CACHE, show_spinner=False)
def datasets_complets(username):
    """Retourne les chemins des datasets autorisés dont l'état est Complet."""
    return lister_datasets_complets(get_users_collection(), username)


@st.cache_data(ttl=DUREE_CACHE, show_spinner=False)
def stats_du_dataset(chemin_dataset):
    """Retourne les statistiques d'un dataset (cubes, masques, RGB, splits)."""
    return calculer_stats(chemin_dataset)


@st.cache_data(ttl=DUREE_CACHE, show_spinner=False)
def versions_du_dataset(chemin_dataset):
    """Retourne les versions préparées d'un dataset, ou None si serveur injoignable."""
    return lire_versions(chemin_dataset)


@st.cache_data(ttl=DUREE_CACHE, show_spinner=False)
def dimensions_du_dataset(chemin_dataset):
    """Retourne les dimensions de tous les cubes du dataset, par split."""
    return lire_dimensions_dataset(chemin_dataset)
