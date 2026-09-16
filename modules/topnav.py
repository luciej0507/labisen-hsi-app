"""
modules/topnav.py — Barre de navigation horizontale personnalisée.

Streamlit n'offre pas nativement de menu horizontal en haut de page
(st.navigation ne propose que position="sidebar" ou "hidden"). Ce module
reconstruit un menu horizontal avec st.page_link, à appeler en haut de
chaque page de l'appli, juste après st.set_page_config().
"""

import streamlit as st

# Liste des pages du menu : (chemin du fichier, libellé affiché)
# Le chemin est relatif au fichier d'entrée de l'appli (Home.py).
PAGES = [
    ("home.py", "Mot d'accueil"),
    ("pages/1_mode_emploi.py", "Mode d'emploi"),
    ("pages/2_connexion.py", "Connexion"),
    # Ajoute ici les futures pages, ex :
    # ("pages/3_Admin_Dashboard.py", "🛠️ Admin"),
    # ("pages/4_User_Dashboard.py", "👤 Espace utilisateur"),
]


def render_topnav() -> None:
    """Affiche le menu horizontal en haut de la page courante."""
    cols = st.columns(len(PAGES))
    for col, (path, label) in zip(cols, PAGES):
        with col:
            st.page_link(path, label=label)
    st.divider()