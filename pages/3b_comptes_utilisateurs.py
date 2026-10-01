"""
3b_comptes_utilisateurs.py : gestion des comptes (espace administrateur).

Permet de consulter la liste des comptes, puis, en cliquant sur une
ligne, de modifier le compte, de définir son mot de passe ou de le
supprimer.

Cette page ne contient que de l'affichage Streamlit. La logique métier
(validation, écriture en base) est dans modules/users.py.
"""

import streamlit as st
from pymongo.errors import DuplicateKeyError

from modules.auth import require_role
from modules.datasets import DATASETS_REMOTE_PATH, chemin_relatif
from modules.db_mongo import get_users_collection
from modules.user_import import ROLES
from modules.users import (
    delete_blocked_reason,
    delete_user,
    format_date,
    is_password_pending,
    reset_password,
    update_user,
    validate_new_password,
    validate_user_update,
)
from ui.arbre_datasets import afficher_arborescence_datasets, lire_selection
from ui.flash import flash, render_flash
from ui.sidebar import SECTIONS_ADMIN, render_sidebar
from ui.topnav import configurer_page, render_topnav
from ui.users_cache import ensure_username_index_once

configurer_page("Espace Admin")

render_topnav("Administration")

require_role("admin")

render_sidebar("Comptes utilisateurs", SECTIONS_ADMIN, "Administration")


# ---------------------------------------------------------------------------
# État de session propre à cette page
# ---------------------------------------------------------------------------

# comptes_table_id : compteur qui change la clé du tableau des comptes, ce
# qui efface la ligne sélectionnée (utilisé après une suppression).
st.session_state.setdefault("comptes_table_id", 0)


# ---------------------------------------------------------------------------
# Boîte de dialogue de suppression
# ---------------------------------------------------------------------------


@st.dialog("Confirmer la suppression")
def dialog_delete_user(username: str) -> None:
    """Fenêtre de confirmation de suppression d'un compte."""
    users = get_users_collection()
    user = users.find_one({"username": username})

    if user is None:
        st.warning("Ce compte n'existe plus.")
        if st.button("Fermer"):
            st.rerun()
        return

    # Certaines suppressions sont interdites (par exemple le dernier admin)
    reason = delete_blocked_reason(users, user, st.session_state.get("username"))
    if reason:
        st.error(reason)
        if st.button("Fermer"):
            st.rerun()
        return

    st.write(
        "Vous allez supprimer définitivement le compte **"
        + username
        + "** ("
        + user.get("prenom", "")
        + " "
        + user.get("nom", "")
        + "). Cette action est irréversible."
    )

    col_confirm, col_cancel = st.columns(2)
    with col_confirm:
        if st.button("Confirmer la suppression", type="primary", width="stretch"):
            if delete_user(users, user["_id"]):
                flash("success", "Compte supprimé avec succès : " + username, "comptes")
                # Les lignes du tableau ont changé de position : on efface la sélection
                st.session_state["comptes_table_id"] += 1
            else:
                flash("error", "Le compte n'a pas pu être supprimé.", "comptes")
            st.rerun()
    with col_cancel:
        if st.button("Annuler", width="stretch"):
            st.rerun()


# ---------------------------------------------------------------------------
# Affichage de la page
# ---------------------------------------------------------------------------


def render_accounts(users) -> None:
    """Tableau des comptes, puis détail du compte sélectionné."""
    render_flash("comptes")

    # Tri par _id : l'ordre des comptes (donc la position des lignes du
    # tableau) reste stable, même si un identifiant est modifié.
    all_users = list(users.find({}).sort("_id", 1))

    st.write("Nombre de comptes : " + str(len(all_users)))

    if len(all_users) == 0:
        st.info("Aucun compte à gérer.")
        return

    # Une ligne par compte. Les datasets sont résumés par leur nombre : la
    # liste complète s'affiche sous le tableau quand on clique sur une ligne.
    rows = []
    for u in all_users:
        rows.append(
            {
                "Nom": u.get("nom", ""),
                "Prénom": u.get("prenom", ""),
                "Email": u.get("email") or "",
                "Identifiant": u.get("username", ""),
                "Rôle": u.get("role", ""),
                "Nb datasets": len(u.get("datasets_access", [])),
                "Statut": "En attente de mot de passe" if is_password_pending(u) else "Actif",
                "Créé le": format_date(u.get("created_at")),
            }
        )

    # Un clic sur une ligne sélectionne le compte. La clé du tableau change
    # après une suppression (voir dialog_delete_user) pour effacer la sélection.
    evenement = st.dataframe(
        rows,
        width="stretch",
        hide_index=True,
        placeholder="",
        on_select="rerun",
        selection_mode="single-row",
        key=f"table_comptes_{st.session_state['comptes_table_id']}",
    )
    lignes_selectionnees = evenement.selection.rows

    if not lignes_selectionnees or lignes_selectionnees[0] >= len(all_users):
        st.info("Cliquez sur une ligne du tableau pour consulter, modifier ou supprimer un compte.")
        return

    selected_user = all_users[lignes_selectionnees[0]]
    selected_username = selected_user["username"]
    uid = str(selected_user["_id"])

    # -- Détail du compte sélectionné ----------------------------------------
    st.divider()
    st.markdown("### Compte sélectionné : " + selected_username)

    # Datasets enregistrés en base, affichés sans la racine, un par ligne
    datasets_actuels = selected_user.get("datasets_access", [])
    st.write(f"Datasets actuellement autorisés ({len(datasets_actuels)})")
    if datasets_actuels:
        st.text(
            "\n".join(
                chemin_relatif(DATASETS_REMOTE_PATH, chemin)
                for chemin in sorted(datasets_actuels)
            )
        )
    else:
        st.caption("Aucun dataset autorisé.")

    current_username = st.session_state.get("username")
    nb_admins = users.count_documents({"role": "admin"})

    # -- Modification -------------------------------------------------------
    st.markdown("### Modifier le compte")

    # Les clés contiennent l'_id du compte : elles restent stables même si
    # le username est modifié, et ne se mélangent pas d'un compte à l'autre.
    edit_username = st.text_input(
        "Nom d'utilisateur (identifiant de connexion)",
        value=selected_user.get("username", ""),
        key=f"edit_username_{uid}",
    )
    edit_nom = st.text_input(
        "Nom", value=selected_user.get("nom", ""), key=f"edit_nom_{uid}"
    )
    edit_prenom = st.text_input(
        "Prénom", value=selected_user.get("prenom", ""), key=f"edit_prenom_{uid}"
    )
    edit_email = st.text_input(
        "Email",
        value=selected_user.get("email", "") or "",
        key=f"edit_email_{uid}",
    )
    edit_role = st.selectbox(
        "Rôle",
        list(ROLES),
        index=list(ROLES).index(selected_user.get("role", "user")),
        key=f"edit_role_{uid}",
    )

    # Sélection des datasets, précochée selon ceux déjà autorisés.
    st.write("Datasets autorisés")
    deja_autorises = selected_user.get("datasets_access", [])
    prefixe_dataset = f"edit_dataset_{uid}_"
    afficher_arborescence_datasets(DATASETS_REMOTE_PATH, prefixe_dataset, deja_autorises)

    # Le bouton est en dernière position, sous les datasets.
    modifier_submit = st.button(
        "Enregistrer les modifications", type="primary", key=f"edit_submit_{uid}"
    )

    if modifier_submit:
        edit_datasets_access = lire_selection(prefixe_dataset)
        error = validate_user_update(
            users, selected_user, edit_username, edit_nom, edit_prenom, edit_role, nb_admins
        )
        if error:
            st.error(error)
        else:
            try:
                updated = update_user(
                    users,
                    user_id=selected_user["_id"],
                    new_username=edit_username,
                    new_nom=edit_nom,
                    new_prenom=edit_prenom,
                    new_email=edit_email,
                    new_role=edit_role,
                    datasets_access=edit_datasets_access,
                )
            except DuplicateKeyError:
                st.error("Ce nom d'utilisateur est déjà utilisé par un autre compte.")
            else:
                if not updated:
                    st.error("Ce compte n'existe plus.")
                else:
                    new_username = edit_username.strip()
                    # Si l'admin renomme son propre compte, on met à jour sa
                    # session pour que les contrôles de suppression restent
                    # corrects.
                    if selected_username == current_username:
                        st.session_state["username"] = new_username
                    # La sélection sera relue depuis la base au prochain affichage.
                    st.session_state.pop(f"{prefixe_dataset}selection", None)
                    st.session_state.pop(f"{prefixe_dataset}ouverts", None)
                    flash(
                        "success",
                        "Compte modifié avec succès : " + new_username,
                        "comptes",
                    )
                    st.rerun()

    # -- Mot de passe -------------------------------------------------------
    st.markdown("### Mot de passe")

    if is_password_pending(selected_user):
        st.info(
            "Ce compte est en attente : il ne peut pas se connecter tant "
            "qu'un mot de passe n'a pas été défini."
        )
    else:
        st.caption(
            "Le mot de passe actuel n'est pas consultable. En saisir un "
            "nouveau ci-dessous remplacera l'ancien."
        )

    # Le formulaire se vide tout seul après validation (clear_on_submit),
    # pour ne pas laisser le mot de passe affiché dans les champs.
    with st.form(f"password_form_{uid}", clear_on_submit=True):
        new_password = st.text_input(
            "Nouveau mot de passe", type="password", key=f"pwd_new_{uid}"
        )
        new_password_confirm = st.text_input(
            "Confirmer le nouveau mot de passe",
            type="password",
            key=f"pwd_confirm_{uid}",
        )
        password_submit = st.form_submit_button("Définir le mot de passe", type="primary")

    if password_submit:
        error = validate_new_password(new_password, new_password_confirm)
        if error:
            st.error(error)
        elif reset_password(users, selected_user["_id"], new_password):
            flash(
                "success",
                "Mot de passe défini pour le compte : " + selected_username,
                "comptes",
            )
            st.rerun()
        else:
            st.error("Ce compte n'existe plus.")

    # -- Suppression --------------------------------------------------------
    st.markdown("### Supprimer le compte")

    if st.button("Supprimer le compte"):
        dialog_delete_user(selected_username)


# ---------------------------------------------------------------------------
# Mise en page
# ---------------------------------------------------------------------------

ensure_username_index_once()
users_collection = get_users_collection()

st.title("Comptes utilisateurs")

render_accounts(users_collection)