"""
Page Connexion.

Formulaires de connexion Admin et User. Utilise modules/auth.py pour
verifier les identifiants et gerer la session.
"""

import streamlit as st

from modules.auth import authenticate, login_user
from modules.topnav import render_topnav

st.set_page_config(page_title="Connexion")

render_topnav()

st.title("Connexion")

st.markdown("Choisissez votre type de connexion pour acceder à votre espace.")

tab_admin, tab_user = st.tabs(["Administrateur", "Utilisateur"])

with tab_admin:
    with st.form("form_login_admin"):
        admin_username = st.text_input("Nom d'utilisateur", key="admin_username")
        admin_password = st.text_input(
            "Mot de passe", type="password", key="admin_password"
        )
        admin_submit = st.form_submit_button("Se connecter")

    if admin_submit:
        user = authenticate(admin_username, admin_password)
        if user is not None and user["role"] == "admin":
            login_user(user)
            st.success("Connexion reussie.")
            st.switch_page("pages/3_admin_dashboard.py")
        else:
            st.error("Identifiants incorrects.")

with tab_user:
    with st.form("form_login_user"):
        user_username = st.text_input("Nom d'utilisateur", key="user_username")
        user_password = st.text_input(
            "Mot de passe", type="password", key="user_password"
        )
        user_submit = st.form_submit_button("Se connecter")

    if user_submit:
        user = authenticate(user_username, user_password)
        if user is not None and user["role"] == "user":
            login_user(user)
            st.success("Connexion reussie.")
            st.info("Espace utilisateur non encore disponible.")
        else:
            st.error("Identifiants incorrects.")