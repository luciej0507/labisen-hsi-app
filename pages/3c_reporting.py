"""
3c_reporting.py : reporting de l'espace administrateur.

Page encore vide : elle accueillera les alertes et le suivi d'activité.
"""

import streamlit as st

from modules.auth import require_role
from ui.sidebar import SECTIONS_ADMIN, render_sidebar
from ui.topnav import configurer_page, render_topnav

configurer_page("Espace Admin")

render_topnav("Administration")

require_role("admin")

render_sidebar("Reporting", SECTIONS_ADMIN, "Administration")

st.title("Reporting")
st.write("En projet")