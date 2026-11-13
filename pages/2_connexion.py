"""
Page Connexion.

Un seul formulaire de connexion, avec un sélecteur de profil (Administrateur
ou Utilisateur) placé au-dessus. Le titre, le texte d'introduction, le sélecteur
et le formulaire sont regroupés dans une colonne centrale pour rester alignés.
Utilise modules/comptes/auth.py pour vérifier les identifiants et gérer la session.
"""

import streamlit as st

from modules.comptes.auth import authenticate_with_role, login_user
from ui.topnav import configurer_page, render_topnav

configurer_page("Connexion")

render_topnav("Connexion")

# Pour chaque profil : le rôle attendu et la page vers laquelle rediriger
PROFILS = {
    "Administrateur": ("admin", "pages/3_admin_dashboard.py"),
    "Utilisateur": ("user", "pages/4_user_dashboard.py"),
}

# Trois colonnes de proportions 1 / 2 / 1 : tout le contenu est placé dans celle du milieu
col_gauche, col_centre, col_droite = st.columns([1, 2, 1])

with col_centre:
    st.title("Connexion")

    st.markdown("Choisissez votre type de connexion pour accéder à votre espace.")

    # Sélecteur du profil (hors du formulaire pour que le choix soit pris en compte immédiatement)
    # Le profil "Utilisateur" est présélectionné à l'ouverture de la page
    profil = st.segmented_control(
        "Type de connexion", list(PROFILS.keys()), default="Utilisateur"
    )

    # Si le bouton est désélectionné, la valeur est None : on arrête la page avec un message
    if profil is None:
        st.info("Veuillez choisir un type de connexion.")
        st.stop()

    role, page = PROFILS[profil]

    # Formulaire unique de connexion
    with st.form("form_login"):
        username = st.text_input("Identifiant")
        password = st.text_input("Mot de passe", type="password")
        submit = st.form_submit_button("Se connecter")

    # Vérification des identifiants au clic sur le bouton
    if submit:
        user = authenticate_with_role(username, password, role)
        if user is not None:
            login_user(user)
            st.success("Connexion réussie.")
            st.switch_page(page)
        else:
            st.error("Identifiants incorrects.")