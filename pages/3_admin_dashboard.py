"""
3_admin_dashboard.py : page d'accueil de l'espace administrateur.

Accessible uniquement aux comptes avec le rôle admin. Le contenu de
cette page est encore à définir. Les fonctionnalités de gestion sont
dans les pages 3a (ajout), 3b (comptes) et 3c (reporting).
"""

import streamlit as st

from modules.auth import require_role
from ui.sidebar import SECTIONS_ADMIN, render_sidebar
from ui.topnav import configurer_page, render_topnav

configurer_page("Espace Admin")

render_topnav("Administration")

require_role("admin")

render_sidebar("Accueil", SECTIONS_ADMIN, "Administration")

st.title("Espace Administrateur")
st.info("En projet.")