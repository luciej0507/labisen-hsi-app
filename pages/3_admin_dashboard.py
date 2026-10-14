"""
3_admin_dashboard.py : page d'accueil de l'espace administrateur.

Accessible uniquement aux comptes avec le rôle admin. Affiche le nombre
de comptes en attente de mot de passe. Les fonctionnalités de gestion
sont dans les pages 3a (ajout), 3b (comptes) et 3c (reporting).
"""

import streamlit as st

from modules.auth import require_role
from modules.db_mongo import get_users_collection
from modules.users import count_pending_users
from ui.sidebar import SECTIONS_ADMIN, render_sidebar
from ui.topnav import configurer_page, render_topnav

configurer_page("Espace Admin")

render_topnav("Administration")

require_role("admin")

render_sidebar("Accueil", SECTIONS_ADMIN, "Administration")

st.title("Espace Administrateur")

# Récupération de la collection puis comptage des comptes en attente
users = get_users_collection()
nombre_en_attente = count_pending_users(users)

# Trois colonnes de même largeur : la carte n'occupe que la première,
# les deux autres restent libres pour de futures cartes
col1, col2, col3 = st.columns(3)

with col1:
    # border=True dessine la carte (bordure arrondie autour du contenu)
    with st.container(border=True):
        st.metric("Comptes en attente de mot de passe", nombre_en_attente)
        
        # Lien cliquable vers la page de gestion des comptes
        st.page_link(
            "pages/3b_comptes_utilisateurs.py",
            label="Aller à la page Comptes utilisateurs",
            icon=":material/group:",
        )