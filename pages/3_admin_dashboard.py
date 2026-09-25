"""
3_admin_dashboard.py : Page Admin Dashboard.

Accessible uniquement aux comptes avec le rôle admin. Contient les
onglets de gestion des utilisateurs : ajout (unitaire ou import CSV),
comptes utilisateurs (consultation, modification, suppression), reporting.

Cette page ne contient que de l'affichage Streamlit et l'appel aux
fonctions de modules/users.py et modules/user_import.py. La logique
métier (validation, écriture en base) vit dans ces modules pour rester
testable independamment de Streamlit.
"""

import streamlit as st
from pymongo.errors import DuplicateKeyError

from modules.auth import require_role
from modules.datasets import DATASETS_REMOTE_PATH, list_folder_contents
from modules.db_mongo import get_users_collection
from ui.flash import flash, render_flash
from ui.topnav import render_topnav
from modules.user_import import (
    ROLES,
    build_recap_csv,
    build_template_csv,
    clean_dataframe,
    parse_csv,
    validate_rows,
)
from modules.users import (
    create_user,
    create_users_from_rows,
    delete_blocked_reason,
    delete_user,
    ensure_username_index,
    format_date,
    update_user,
    validate_new_user,
    validate_user_update,
)

st.set_page_config(page_title="Espace Admin", layout="wide")

render_topnav("Administration")

require_role("admin")


# ---------------------------------------------------------------------------
# Etat de session propre a cette page
# ---------------------------------------------------------------------------

# ajout_form_id : compteur qui change les cles des widgets du formulaire
# d'ajout, ce qui le remet a zero (nouveau formulaire vierge).
st.session_state.setdefault("ajout_form_id", 0)
# ajout_created : recapitulatif du dernier compte cree (None si aucun).
st.session_state.setdefault("ajout_created", None)
# import_id : meme principe pour le file_uploader et l'editeur de l'import CSV.
st.session_state.setdefault("import_id", 0)
# import_result : bilan du dernier import CSV (None si aucun).
st.session_state.setdefault("import_result", None)


# ---------------------------------------------------------------------------
# Cache Streamlit autour de la logique metier
# ---------------------------------------------------------------------------


@st.cache_resource
def ensure_username_index_once() -> bool:
    """
    Enveloppe Streamlit autour de ensure_username_index (modules/users.py),
    pour que l'index ne soit créé qu'une seule fois par processus.
    """
    return ensure_username_index(get_users_collection())


# ---------------------------------------------------------------------------
# Boite de dialogue de suppression
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
            else:
                flash("error", "Le compte n'a pas pu être supprimé.", "comptes")
            st.rerun()
    with col_cancel:
        if st.button("Annuler", width="stretch"):
            st.rerun()


# ---------------------------------------------------------------------------
# Affichage des datasets, niveau par niveau (utilise par les deux formulaires)
# ---------------------------------------------------------------------------


def afficher_arborescence_datasets(chemin: str, prefixe_cle: str,
                                    deja_autorises: list, profondeur: int = 0) -> None:
    """
    Affiche le contenu d'un dossier du serveur, avec une case a cocher par
    element (dataset, sous-dossier ou fichier).

    Un sous-dossier n'est parcouru sur le serveur que si l'admin coche
    "Explorer" pour ce sous-dossier precis (chargement a la demande,
    niveau par niveau), pour rester rapide meme sur de gros dossiers.

    Les cases sont ajoutees a st.session_state via leur cle
    (prefixe_cle + chemin de l'element), relue au moment de la
    validation du formulaire correspondant.
    """
    elements = list_folder_contents(chemin)
    if not elements and profondeur == 0:
        st.info("Aucun dataset trouvé sur le serveur.")

    for element in elements:
        indentation = "    " * profondeur
        cle = f"{prefixe_cle}{element['chemin']}"

        if not element["est_dossier"]:
            # Fichier : une seule case a cocher, pas d'exploration possible.
            st.checkbox(
                f"{indentation}{element['nom']}",
                value=element["chemin"] in deja_autorises,
                key=cle,
            )
            continue

        # Dossier : une case pour l'autoriser, et une case "Explorer" pour
        # charger son contenu (un seul niveau a la fois).
        colonne_case, colonne_exploration = st.columns([4, 1])
        with colonne_case:
            st.checkbox(
                f"{indentation}{element['nom']}",
                value=element["chemin"] in deja_autorises,
                key=cle,
            )
        with colonne_exploration:
            explorer = st.checkbox(
                "Explorer",
                key=f"explorer_{cle}",
            )
        if explorer:
            afficher_arborescence_datasets(
                element["chemin"], prefixe_cle, deja_autorises, profondeur + 1
            )


# ---------------------------------------------------------------------------
# Onglet Ajout utilisateur : un seul utilisateur
# ---------------------------------------------------------------------------


def render_add_single(users) -> None:
    created = st.session_state.get("ajout_created")

    # Compte tout juste cree : recapitulatif a la place du formulaire.
    if created:
        st.success("Compte crée avec succès : " + created["username"])
        st.write(
            f"Nom : {created['prenom']} {created['nom']}  \n"
            f"Role : {created['role']}  \n"
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
        new_role = st.selectbox("Role", list(ROLES), key=f"ajout_role_{fid}")

        ajout_submit = st.form_submit_button("Créer le compte")

    # Selection des datasets : affichee sous le formulaire, mais toujours
    # HORS de celui-ci. A l'interieur d'un st.form, aucun widget ne
    # provoque de rafraichissement tant que le formulaire n'est pas
    # valide : deplier un sous-dossier n'aurait donc aucun effet visible
    # avant la creation du compte.
    st.write("Datasets autorisés")
    prefixe_dataset = f"ajout_dataset_{fid}_"
    afficher_arborescence_datasets(DATASETS_REMOTE_PATH, prefixe_dataset, [])

    if not ajout_submit:
        return

    # Les datasets coches sont recuperes a partir des cases affichees
    # ci-dessus, en repérant leurs cles par prefixe.
    new_datasets_access = [
        cle[len(prefixe_dataset):]
        for cle, valeur in st.session_state.items()
        if cle.startswith(prefixe_dataset) and valeur
    ]

    # Validation faite dans modules/users.py : testable sans Streamlit.
    error = validate_new_user(
        new_nom, new_prenom, new_username, new_password, new_password_confirm, users
    )
    if error:
        st.error(error)
        return

    try:
        created = create_user(
            users,
            nom=new_nom,
            prenom=new_prenom,
            email=new_email,
            username=new_username,
            password=new_password,
            role=new_role,
            datasets_access=new_datasets_access,
        )
    except DuplicateKeyError:
        # Cas rare : deux clics simultanes ont passe la verification
        # ci-dessus en meme temps, l'index unique en base tranche.
        st.error("Ce nom d'utilisateur existe déjà.")
        return

    st.session_state["ajout_created"] = created
    st.rerun()


# ---------------------------------------------------------------------------
# Onglet Ajout utilisateur : import CSV
# ---------------------------------------------------------------------------


def render_import_result(result: dict) -> None:
    """Bilan affiche après un import, avec le récapitulatif à télécharger."""
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
        "généré pour chaque compte, et vous récuperez la liste à la fin de "
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
    col_ko.metric("Lignes a corriger", len(rejected_rows))

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
        # Nouvelle cle pour vider le file_uploader et l'editeur.
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

    # Le selectbox est pilote par session_state pour pouvoir suivre un compte
    # renomme, et retomber sur le premier compte si celui qui etait
    # selectionne vient d'etre supprime. Ces affectations doivent avoir lieu
    # avant la creation du widget.
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

    # Les cles contiennent l'_id du compte : elles restent stables meme si
    # le username est modifie, et ne se melangent pas d'un compte a l'autre.
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
        modifier_submit = st.form_submit_button("Enregistrer les modifications")

    # Selection des datasets : affichee sous le formulaire, mais toujours
    # HORS de celui-ci (voir le commentaire dans render_add_single).
    # Precochee selon les datasets deja autorises pour ce compte.
    st.write("Datasets autorisés")
    deja_autorises = selected_user.get("datasets_access", [])
    prefixe_dataset = f"edit_dataset_{uid}_"
    afficher_arborescence_datasets(DATASETS_REMOTE_PATH, prefixe_dataset, deja_autorises)

    if modifier_submit:
        # Les datasets coches sont recuperes a partir des cases affichees
        # plus haut, hors du formulaire, en repérant leurs cles par prefixe.
        edit_datasets_access = [
            cle[len(prefixe_dataset):]
            for cle, valeur in st.session_state.items()
            if cle.startswith(prefixe_dataset) and valeur
        ]
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
                    # Si l'admin renomme son propre compte, on met a jour sa
                    # session pour que les controles de suppression restent
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

ensure_username_index_once()
users_collection = get_users_collection()

st.title("Espace Administrateur")

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
    st.write("A venir : alertes et suivi d'activité.")