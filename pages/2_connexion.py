"""
Page Connexion.

Formulaires de connexion Admin et User cote a cote. Utilise modules/auth.py
pour verifier les identifiants et gerer la session.
"""

import streamlit as st

from modules.auth import authenticate_with_role, login_user
from modules.topnav import render_topnav

st.set_page_config(page_title="Connexion")

render_topnav("Connexion")

st.title("Connexion")

st.markdown("Choisissez votre type de connexion pour accéder à votre espace.")


def formulaire(titre, role, page):
    st.subheader(titre)
    with st.form("form_login_" + role):
        username = st.text_input("Nom d'utilisateur", key=role + "_username")
        password = st.text_input("Mot de passe", type="password", key=role + "_password")
        submit = st.form_submit_button("Se connecter")

    if submit:
        user = authenticate_with_role(username, password, role)
        if user is not None:
            login_user(user)
            st.success("Connexion réussie.")
            st.switch_page(page)
        else:
            st.error("Identifiants incorrects.")


col_admin, col_user = st.columns(2)

with col_admin:
    formulaire("Administrateur", "admin", "pages/3_admin_dashboard.py")

with col_user:
    formulaire("Utilisateur", "user", "pages/4_user_dashboard.py")