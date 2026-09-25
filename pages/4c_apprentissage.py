"""
Page Apprentissage : section de l'espace de travail (rôle user).
"""

import streamlit as st

from modules.auth import require_role
from ui.sidebar import render_sidebar
from ui.topnav import render_topnav

st.set_page_config(page_title="Apprentissage", layout="wide")

render_topnav("Mon Espace")
require_role("user")
render_sidebar("Apprentissage")

st.title("Apprentissage")
st.write("À venir")