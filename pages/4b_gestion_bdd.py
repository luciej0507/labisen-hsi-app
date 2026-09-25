"""
Page Gestion des BDD : section de l'espace de travail (rôle user).
"""

import streamlit as st

from modules.auth import require_role
from ui.sidebar import render_sidebar
from ui.topnav import render_topnav

st.set_page_config(page_title="Gestion des BDD", layout="wide")

render_topnav("Mon Espace")
require_role("user")
render_sidebar("Gestion des BDD")

st.title("Gestion des bases de données")
st.write("À venir")