"""
Page Admin Dashboard.

Accessible uniquement aux comptes avec le role admin. Contient les
onglets de gestion des utilisateurs : ajout, comptes utilisateurs
(consultation, modification, suppression), reporting.
"""

from datetime import datetime, timezone

import bcrypt
import streamlit as st

from modules.auth import get_current_role, logout_user, require_role
from modules.db_mongo import get_users_collection
from modules.topnav import render_topnav

st.set_page_config(page_title="Espace Admin")

render_topnav()

require_role("admin")

st.title("Espace Administrateur")

col_info, col_logout = st.columns([4, 1])
with col_info:
    st.write("Connecte en tant que : " + str(st.session_state.get("username")))
with col_logout:
    if st.button("Se déconnecter"):
        logout_user()
        st.switch_page("home.py")

st.divider()

tab_ajout, tab_comptes, tab_reporting = st.tabs(
    ["Ajout utilisateur", "Comptes utilisateurs", "Reporting"]
)


# Onglet Ajout utilisateur
with tab_ajout:
    st.subheader("Ajout d'un utilisateur")

    with st.form("form_ajout_user"):
        new_nom = st.text_input("Nom")
        new_prenom = st.text_input("Prenom")
        new_email = st.text_input("Email (optionnel)")
        new_username = st.text_input("Nom d'utilisateur (identifiant de connexion)")
        new_password = st.text_input("Mot de passe", type="password")
        new_password_confirm = st.text_input(
            "Confirmer le mot de passe", type="password"
        )
        new_role = st.selectbox("Role", ["user", "admin"])
        new_datasets = st.text_input(
            "Datasets autorises (separes par une virgule, optionnel)"
        )
        ajout_submit = st.form_submit_button("Creer le compte")

    if ajout_submit:
        users = get_users_collection()

        if not new_nom.strip():
            st.error("Le nom ne peut pas etre vide.")
        elif not new_prenom.strip():
            st.error("Le prenom ne peut pas etre vide.")
        elif not new_username.strip():
            st.error("Le nom d'utilisateur ne peut pas etre vide.")
        elif not new_password:
            st.error("Le mot de passe ne peut pas etre vide.")
        elif new_password != new_password_confirm:
            st.error("Les mots de passe ne correspondent pas.")
        elif users.find_one({"username": new_username}):
            st.error("Ce nom d'utilisateur existe deja.")
        else:
            datasets_access = [
                d.strip() for d in new_datasets.split(",") if d.strip()
            ]
            password_hash = bcrypt.hashpw(
                new_password.encode("utf-8"), bcrypt.gensalt()
            )
            users.insert_one(
                {
                    "nom": new_nom.strip(),
                    "prenom": new_prenom.strip(),
                    "email": new_email.strip() or None,
                    "username": new_username,
                    "password_hash": password_hash.decode("utf-8"),
                    "role": new_role,
                    "datasets_access": datasets_access,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            st.success("Compte crée avec succès : " + new_username)



# Onglet Comptes utilisateurs
with tab_comptes:
    st.subheader("Comptes utilisateurs")

    users = get_users_collection()
    all_users = list(users.find({}))

    st.write("Nombre de comptes : " + str(len(all_users)))

    rows = []
    for u in all_users:
        rows.append(
            {
                "nom": u.get("nom", ""),
                "prenom": u.get("prenom", ""),
                "email": u.get("email", ""),
                "username": u.get("username", ""),
                "role": u.get("role", ""),
                "datasets_access": ", ".join(u.get("datasets_access", [])),
                "created_at": str(u.get("created_at", "")),
            }
        )

    st.dataframe(rows, width='stretch')

    st.divider()
    st.write("Sélectionner un compte pour le modifier ou le supprimer")

    if len(all_users) == 0:
        st.info("Aucun compte à gérer.")
    else:
        usernames = [u["username"] for u in all_users]
        selected_username = st.selectbox("Compte", usernames)
        selected_user = users.find_one({"username": selected_username})

        current_username = st.session_state.get("username")
        nb_admins = users.count_documents({"role": "admin"})

        st.markdown("### Modifier le compte")

        with st.form("form_modifier_user"):
            edit_nom = st.text_input("Nom", value=selected_user.get("nom", ""))
            edit_prenom = st.text_input("Prenom", value=selected_user.get("prenom", ""))
            edit_email = st.text_input("Email", value=selected_user.get("email", "") or "")
            edit_role = st.selectbox(
                "Role",
                ["user", "admin"],
                index=["user", "admin"].index(selected_user.get("role", "user")),
            )
            edit_datasets = st.text_input(
                "Datasets autorisés (séparés par une virgule)",
                value=", ".join(selected_user.get("datasets_access", [])),
            )
            modifier_submit = st.form_submit_button("Enregistrer les modifications")

        if modifier_submit:
            if selected_user.get("role") == "admin" and edit_role == "user" and nb_admins <= 1:
                st.error("Impossible de retirer le rôle admin du dernier compte admin.")
            else:
                datasets_access = [
                    d.strip() for d in edit_datasets.split(",") if d.strip()
                ]
                users.update_one(
                    {"username": selected_username},
                    {
                        "$set": {
                            "nom": edit_nom.strip(),
                            "prenom": edit_prenom.strip(),
                            "email": edit_email.strip() or None,
                            "role": edit_role,
                            "datasets_access": datasets_access,
                        }
                    },
                )
                st.success("Compte modifié avec succès.")
                st.rerun()

        st.markdown("### Supprimer le compte")

        confirm_delete = st.checkbox(
            "Je confirme la suppression de ce compte", key="confirm_delete"
        )
        delete_clicked = st.button("Supprimer le compte")

        if delete_clicked:
            if not confirm_delete:
                st.error("Veuillez cocher la case de confirmation avant de supprimer.")
            elif selected_username == current_username:
                st.error("Vous ne pouvez pas supprimer votre propre compte.")
            elif selected_user.get("role") == "admin" and nb_admins <= 1:
                st.error("Impossible de supprimer le dernier compte admin.")
            else:
                users.delete_one({"username": selected_username})
                st.success("Compte supprimé avec succès.")
                st.rerun()

with tab_reporting:
    st.subheader("Reporting")
    st.write("A venir : alertes et suivi d'activite.")