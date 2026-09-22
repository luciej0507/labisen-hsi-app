"""
3_admin_dashboard.py : Page Admin Dashboard.

Accessible uniquement aux comptes avec le role admin. Contient les
onglets de gestion des utilisateurs : ajout (unitaire ou import CSV),
comptes utilisateurs (consultation, modification, suppression), reporting.
"""

from datetime import datetime, timezone
from typing import Optional

import bcrypt
import streamlit as st
from pymongo.errors import DuplicateKeyError, PyMongoError

from modules.auth import get_current_role, logout_user, require_role
from modules.db_mongo import get_users_collection
from modules.flash import flash, render_flash
from modules.topnav import render_topnav
from modules.user_import import (
    ROLES,
    build_recap_csv,
    build_template_csv,
    clean_dataframe,
    generate_temp_password,
    parse_csv,
    parse_datasets,
    validate_rows,
)

st.set_page_config(page_title="Espace Admin")

render_topnav()

require_role("admin")


# ---------------------------------------------------------------------------
# Etat de session propre à cette page
# ---------------------------------------------------------------------------

# ajout_form_id : compteur qui change les clés des widgets du formulaire
# d'ajout, ce qui le remet à zéro (nouveau formulaire vierge).
st.session_state.setdefault("ajout_form_id", 0)
# ajout_created : récapitulatif du dernier compte créé (None si aucun).
st.session_state.setdefault("ajout_created", None)
# import_id : même principe pour le file_uploader et l'éditeur de l'import CSV.
st.session_state.setdefault("import_id", 0)
# import_result : bilan du dernier import CSV (None si aucun).
st.session_state.setdefault("import_result", None)


# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------


@st.cache_resource
def ensure_username_index() -> bool:
    """
    Crée (une fois par process) un index unique sur username, pour que
    MongoDB refuse lui-même les doublons même en cas de clics simultanés.
    Retourne False si l'index n'a pas pu être créé (doublons déjà présents
    en base, par exemple) : l'application continue alors de fonctionner
    avec ses vérifications habituelles.
    """
    try:
        get_users_collection().create_index("username", unique=True)
        return True
    except PyMongoError:
        return False


def hash_password(password: str) -> str:
    """Hash bcrypt du mot de passe, prêt à être stocké en base."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def format_date(value) -> str:
    """Date au format JJ/MM/AAAA"""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    return str(value) if value else ""


def delete_blocked_reason(users, user: dict, current_username: str) -> Optional[str]:
    """Retourne la raison qui interdit la suppression, ou None si c'est permis."""
    if user.get("username") == current_username:
        return "Vous ne pouvez pas supprimer votre propre compte."
    if user.get("role") == "admin" and users.count_documents({"role": "admin"}) <= 1:
        return "Impossible de supprimer le dernier compte admin."
    return None


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
            result = users.delete_one({"_id": user["_id"]})
            if result.deleted_count == 1:
                flash("success", "Compte supprimé avec succès : " + username, "comptes")
            else:
                flash("error", "Le compte n'a pas pu être supprimé.", "comptes")
            st.rerun()
    with col_cancel:
        if st.button("Annuler", width="stretch"):
            st.rerun()


# ---------------------------------------------------------------------------
# Onglet Ajout utilisateur : un seul utilisateur
# ---------------------------------------------------------------------------


def render_add_single(users) -> None:
    created = st.session_state.get("ajout_created")

    # Compte tout juste créé : récapitulatif à la place du formulaire.
    if created:
        st.success("Compte créé avec succès : " + created["username"])
        st.write(
            f"Nom : {created['prenom']} {created['nom']}  \n"
            f"Rôle : {created['role']}  \n"
            f"Datasets autorisés : {', '.join(created['datasets_access']) or 'aucun'}"
        )
        if st.button("Ajouter un nouvel utilisateur", type="primary"):
            st.session_state["ajout_created"] = None
            st.session_state["ajout_form_id"] += 1
            st.rerun()
        return

    fid = st.session_state["ajout_form_id"]

    with st.form(f"form_ajout_user_{fid}"):
        new_nom = st.text_input("Nom", key=f"ajout_nom_{fid}")
        new_prenom = st.text_input("Prénom", key=f"ajout_prenom_{fid}")
        new_email = st.text_input("Email (optionnel)", key=f"ajout_email_{fid}")
        new_username = st.text_input(
            "Nom d'utilisateur (identifiant de connexion)", key=f"ajout_username_{fid}"
        )
        new_password = st.text_input(
            "Mot de passe", type="password", key=f"ajout_password_{fid}"
        )
        new_password_confirm = st.text_input(
            "Confirmer le mot de passe",
            type="password",
            key=f"ajout_password_confirm_{fid}",
        )
        new_role = st.selectbox("Rôle", list(ROLES), key=f"ajout_role_{fid}")
        new_datasets = st.text_input(
            "Datasets autorisés (séparés par une virgule, optionnel)",
            key=f"ajout_datasets_{fid}",
        )
        ajout_submit = st.form_submit_button("Créer le compte")

    if not ajout_submit:
        return

    username = new_username.strip()

    if not new_nom.strip():
        st.error("Le nom ne peut pas être vide.")
    elif not new_prenom.strip():
        st.error("Le prénom ne peut pas être vide.")
    elif not username:
        st.error("Le nom d'utilisateur ne peut pas être vide.")
    elif not new_password:
        st.error("Le mot de passe ne peut pas être vide.")
    elif new_password != new_password_confirm:
        st.error("Les mots de passe ne correspondent pas.")
    elif users.find_one({"username": username}):
        st.error("Ce nom d'utilisateur existe déjà.")
    else:
        datasets_access = parse_datasets(new_datasets)
        try:
            users.insert_one(
                {
                    "nom": new_nom.strip(),
                    "prenom": new_prenom.strip(),
                    "email": new_email.strip() or None,
                    "username": username,
                    "password_hash": hash_password(new_password),
                    "role": new_role,
                    "datasets_access": datasets_access,
                    "created_at": datetime.now(timezone.utc),
                }
            )
        except DuplicateKeyError:
            st.error("Ce nom d'utilisateur existe déjà.")
            return

        st.session_state["ajout_created"] = {
            "username": username,
            "nom": new_nom.strip(),
            "prenom": new_prenom.strip(),
            "role": new_role,
            "datasets_access": datasets_access,
        }
        st.rerun()


# ---------------------------------------------------------------------------
# Onglet Ajout utilisateur : import CSV
# ---------------------------------------------------------------------------


def create_users_from_rows(users, rows: list) -> tuple:
    """
    Insère les lignes validées, avec un mot de passe temporaire par compte.
    Retourne (created, failed) : created contient les mots de passe
    temporaires en clair (pour le récapitulatif), failed les lignes que
    MongoDB a refusées (doublon apparu entre-temps).
    """
    created = []
    failed = []
    now = datetime.now(timezone.utc)

    for row in rows:
        temp_password = generate_temp_password()
        try:
            users.insert_one(
                {
                    "nom": row["nom"],
                    "prenom": row["prenom"],
                    "email": row["email"],
                    "username": row["username"],
                    "password_hash": hash_password(temp_password),
                    "role": row["role"],
                    "datasets_access": row["datasets_access"],
                    "created_at": now,
                }
            )
        except DuplicateKeyError:
            failed.append(
                {
                    "ligne": row["ligne"],
                    "username": row["username"],
                    "motif": "identifiant déjà utilisé",
                }
            )
            continue

        created.append(
            {
                "nom": row["nom"],
                "prenom": row["prenom"],
                "username": row["username"],
                "role": row["role"],
                "mot_de_passe_temporaire": temp_password,
            }
        )

    return created, failed


def render_import_result(result: dict) -> None:
    """Bilan affiché après un import, avec le récapitulatif à télécharger."""
    if result["created_count"]:
        st.success(f"{result['created_count']} compte(s) créé(s).")
    else:
        st.info("Aucun compte n'a été créé.")

    if result["rejected"]:
        st.warning(f"{len(result['rejected'])} ligne(s) rejetée(s) :")
        st.dataframe(result["rejected"], width="stretch", hide_index=True)

    if result["created_count"]:
        st.warning(
            "Le fichier ci-dessous contient les mots de passe temporaires en "
            "clair. Téléchargez-le maintenant : une fois que vous aurez cliqué "
            "sur Terminer, il ne sera plus récupérable."
        )
        st.download_button(
            "Télécharger le récapitulatif (identifiants et mots de passe)",
            data=result["recap_csv"],
            file_name="recapitulatif_import_utilisateurs.csv",
            mime="text/csv",
            on_click="ignore",
        )

    if st.button("Terminer et faire un nouvel import", type="primary"):
        st.session_state["import_result"] = None
        st.rerun()


def render_add_csv(users) -> None:
    result = st.session_state.get("import_result")
    if result:
        render_import_result(result)
        return

    import_id = st.session_state["import_id"]

    st.write(
        "Créez plusieurs comptes d'un coup à partir d'un fichier CSV. Le mot "
        "de passe n'est pas dans le fichier : un mot de passe temporaire est "
        "généré pour chaque compte, et vous récupérez la liste à la fin de "
        "l'import."
    )
    st.download_button(
        "Télécharger le modèle CSV",
        data=build_template_csv(),
        file_name="modele_import_utilisateurs.csv",
        mime="text/csv",
        on_click="ignore",
    )

    uploaded = st.file_uploader(
        "Fichier CSV", type=["csv"], key=f"import_uploader_{import_id}"
    )
    if uploaded is None:
        return

    try:
        df = parse_csv(uploaded.getvalue())
    except ValueError as exc:
        st.error(str(exc))
        return

    st.write(
        "Vérifiez le contenu et corrigez-le directement dans le tableau si "
        "besoin. Vous pouvez aussi ajouter ou supprimer des lignes."
    )
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        width="stretch",
        hide_index=False,
        key=f"import_editor_{import_id}_{uploaded.name}_{uploaded.size}",
    )

    cleaned = clean_dataframe(edited)
    existing_usernames = {
        u["username"] for u in users.find({}, {"username": 1}) if u.get("username")
    }
    valid_rows, rejected_rows = validate_rows(cleaned, existing_usernames)

    col_ok, col_ko = st.columns(2)
    col_ok.metric("Lignes valides", len(valid_rows))
    col_ko.metric("Lignes à corriger", len(rejected_rows))

    if rejected_rows:
        st.warning(
            "Ces lignes ne seront pas importées tant qu'elles ne sont pas "
            "corrigées dans le tableau ci-dessus :"
        )
        st.dataframe(rejected_rows, width="stretch", hide_index=True)

    if not valid_rows:
        st.info("Aucune ligne valide à importer pour le moment.")
        return

    if st.button(f"Importer {len(valid_rows)} compte(s)", type="primary"):
        with st.spinner("Création des comptes en cours..."):
            created, failed = create_users_from_rows(users, valid_rows)

        st.session_state["import_result"] = {
            "created_count": len(created),
            "rejected": rejected_rows + failed,
            "recap_csv": build_recap_csv(created) if created else b"",
        }
        # Nouvelle clé pour vider le file_uploader et l'éditeur.
        st.session_state["import_id"] += 1
        st.rerun()


# ---------------------------------------------------------------------------
# Onglet Comptes utilisateurs
# ---------------------------------------------------------------------------


def render_accounts(users) -> None:
    render_flash("comptes")

    st.subheader("Comptes utilisateurs")

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
                "created_at": format_date(u.get("created_at")),
            }
        )

    st.dataframe(rows, width="stretch")

    st.divider()
    st.write("Sélectionner un compte pour le modifier ou le supprimer")

    if len(all_users) == 0:
        st.info("Aucun compte à gérer.")
        return

    usernames = [u["username"] for u in all_users]

    # Le selectbox est piloté par session_state pour pouvoir suivre un compte
    # renommé, et retomber sur le premier compte si celui qui était
    # sélectionné vient d'être supprimé. Ces affectations doivent avoir lieu
    # avant la création du widget.
    pending = st.session_state.pop("pending_selected_username", None)
    if pending in usernames:
        st.session_state["compte_selectionne"] = pending
    elif st.session_state.get("compte_selectionne") not in usernames:
        st.session_state["compte_selectionne"] = usernames[0]

    selected_username = st.selectbox("Compte", usernames, key="compte_selectionne")
    selected_user = users.find_one({"username": selected_username})
    uid = str(selected_user["_id"])

    current_username = st.session_state.get("username")
    nb_admins = users.count_documents({"role": "admin"})

    # -- Modification -------------------------------------------------------
    st.markdown("### Modifier le compte")

    # Les clés contiennent l'_id du compte : elles restent stables même si
    # le username est modifié, et ne se mélangent pas d'un compte à l'autre.
    with st.form(f"form_modifier_user_{uid}"):
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
        edit_datasets = st.text_input(
            "Datasets autorisés (séparés par une virgule)",
            value=", ".join(selected_user.get("datasets_access", [])),
            key=f"edit_datasets_{uid}",
        )
        modifier_submit = st.form_submit_button("Enregistrer les modifications")

    if modifier_submit:
        new_username = edit_username.strip()

        if not new_username:
            st.error("Le nom d'utilisateur ne peut pas être vide.")
        elif not edit_nom.strip():
            st.error("Le nom ne peut pas être vide.")
        elif not edit_prenom.strip():
            st.error("Le prénom ne peut pas être vide.")
        elif users.find_one(
            {"username": new_username, "_id": {"$ne": selected_user["_id"]}}
        ):
            st.error("Ce nom d'utilisateur est déjà utilisé par un autre compte.")
        elif (
            selected_user.get("role") == "admin"
            and edit_role == "user"
            and nb_admins <= 1
        ):
            st.error("Impossible de retirer le rôle admin du dernier compte admin.")
        else:
            try:
                result = users.update_one(
                    {"_id": selected_user["_id"]},
                    {
                        "$set": {
                            "username": new_username,
                            "nom": edit_nom.strip(),
                            "prenom": edit_prenom.strip(),
                            "email": edit_email.strip() or None,
                            "role": edit_role,
                            "datasets_access": parse_datasets(edit_datasets),
                        }
                    },
                )
            except DuplicateKeyError:
                st.error("Ce nom d'utilisateur est déjà utilisé par un autre compte.")
            else:
                if result.matched_count == 0:
                    st.error("Ce compte n'existe plus.")
                else:
                    # Si l'admin renomme son propre compte, on met à jour sa
                    # session pour que les contrôles de suppression restent
                    # corrects.
                    if selected_username == current_username:
                        st.session_state["username"] = new_username
                    st.session_state["pending_selected_username"] = new_username
                    flash(
                        "success",
                        "Compte modifié avec succès : " + new_username,
                        "comptes",
                    )
                    st.rerun()

    # -- Suppression --------------------------------------------------------
    st.markdown("### Supprimer le compte")

    if st.button("Supprimer le compte"):
        dialog_delete_user(selected_username)


# ---------------------------------------------------------------------------
# Mise en page
# ---------------------------------------------------------------------------

ensure_username_index()
users_collection = get_users_collection()

st.title("Espace Administrateur")

col_info, col_logout = st.columns([4, 1])
with col_info:
    st.write("Connecté en tant que : " + str(st.session_state.get("username")))
with col_logout:
    if st.button("Se déconnecter"):
        # Le récapitulatif d'import contient des mots de passe temporaires en
        # clair : on ne le garde pas en session après la déconnexion.
        st.session_state["import_result"] = None
        st.session_state["ajout_created"] = None
        logout_user()
        st.switch_page("pages/2_connexion.py")

st.divider()

tab_ajout, tab_comptes, tab_reporting = st.tabs(
    ["Ajout utilisateur", "Comptes utilisateurs", "Reporting"]
)

with tab_ajout:
    st.subheader("Ajout d'un utilisateur")

    mode_ajout = st.radio(
        "Mode d'ajout",
        ["Un utilisateur", "Import CSV"],
        horizontal=True,
        label_visibility="collapsed",
        key="ajout_mode",
    )

    if mode_ajout == "Un utilisateur":
        render_add_single(users_collection)
    else:
        render_add_csv(users_collection)

with tab_comptes:
    render_accounts(users_collection)

with tab_reporting:
    st.subheader("Reporting")
    st.write("A venir : alertes et suivi d'activite.")