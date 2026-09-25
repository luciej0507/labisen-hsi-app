"""
Page Accueil de l'espace de travail : accessible uniquement aux comptes
avec le rôle user. Les autres sections (Acquisition, Gestion des BDD,
Apprentissage) sont dans les pages 4a, 4b et 4c.
"""

import streamlit as st

from modules.auth import require_role
from ui.sidebar import render_sidebar
from ui.topnav import render_topnav

st.set_page_config(page_title="Mon Espace", layout="wide")

render_topnav("Espace de travail")

# Bloque l'accès si l'utilisateur n'est pas connecté avec le rôle "user".
require_role("user")

# Menu latéral (après require_role pour ne pas l'afficher aux non autorisés).
render_sidebar("Accueil")

st.title("Mon Espace")
st.write("À venir")