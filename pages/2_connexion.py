"""
Page "Connexion" : choix entre connexion Admin et connexion User.

Les formulaires de connexion réels (vérification username/mot de passe)
seront branchés plus tard sur modules/auth.py,
une fois la base users en place.
"""

import streamlit as st

st.set_page_config(page_title="Connexion")

from modules.topnav import render_topnav
render_topnav()



st.title("Connexion")

st.markdown("Choisissez votre type de connexion pour accéder à votre espace.")

col_admin, col_user = st.columns(2)

with col_admin:
    st.subheader("Administrateur")
    st.write("Gestion des utilisateurs, suivi et reporting.")
    if st.button("Connexion Admin", use_container_width=True):
        st.session_state["connexion_type"] = "admin"

with col_user:
    st.subheader("Utilisateur")
    st.write("Acquisition et gestion des bases de données.")
    if st.button("Connexion User", use_container_width=True):
        st.session_state["connexion_type"] = "user"

st.divider()

# --- Redirection vers le bon formulaire selon le choix effectué ---
connexion_type = st.session_state.get("connexion_type")

if connexion_type == "admin":
    st.info(
        "🚧 Formulaire de connexion Admin à venir "
        "(sera branché sur pages/3_Admin_Dashboard.py + modules/auth.py)."
    )
    # Une fois la page Admin créée, décommenter :
    # st.switch_page("pages/3_Admin_Dashboard.py")

elif connexion_type == "user":
    st.info(
        "🚧 Formulaire de connexion User à venir "
        "(sera branché sur pages/4_User_Dashboard.py + modules/auth.py)."
    )
    # Une fois la page User créée, décommenter :
    # st.switch_page("pages/4_User_Dashboard.py")