import streamlit as st

from modules.auth import logout_user, require_role
from modules.topnav import render_topnav

st.set_page_config(page_title="Espace utilisateur")

render_topnav("User")

require_role("Connexion")

st.title("Espace de travail")
st.write(f"Connecté en tant que {st.session_state['username']}")

if st.button("Déconnexion"):
    logout_user()
    st.switch_page("pages/2_connexion.py")

tab_acquisition, tab_database = st.tabs(["Acquisition", "Gestion de Base de données"])

# Onglet Acquisition : pas développé pour l'instant
with tab_acquisition:
    st.write("À venir")


# Onglet Gestion de Base de données
with tab_database:
    st.write("À venir")