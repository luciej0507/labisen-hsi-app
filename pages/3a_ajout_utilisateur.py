"""
3a_ajout_utilisateur.py : ajout d'utilisateurs (espace administrateur).

Deux modes : création d'un seul compte via un formulaire, ou création
de plusieurs comptes à partir d'un fichier CSV.

Cette page ne contient que de l'affichage Streamlit. La logique métier
(validation, écriture en base) est dans modules/users.py et
modules/user_import.py.
"""

import streamlit as st
from pymongo.errors import DuplicateKeyError

from modules.auth import require_role
from modules.datasets import DATASETS_REMOTE_PATH
from modules.db_mongo import get_users_collection
from modules.user_import import (
    ROLES,
    build_status_table,
    build_template_csv,
    clean_dataframe,
    parse_csv,
    validate_rows,
)
from modules.users import create_user, create_users_from_rows, validate_new_user
from ui.arbre_datasets import afficher_arborescence_datasets, lire_selection
from ui.sidebar import SECTIONS_ADMIN, render_sidebar
from ui.topnav import configurer_page, render_topnav
from ui.users_cache import ensure_username_index_once

configurer_page("Espace Admin")

render_topnav("Administration")

require_role("admin")

render_sidebar("Ajout utilisateur", SECTIONS_ADMIN, "Administration")


# ---------------------------------------------------------------------------
# État de session propre à cette page
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
# Mode 1 : un seul utilisateur
# ---------------------------------------------------------------------------


def render_add_single(users) -> None:
    """Formulaire de création d'un compte, puis récapitulatif du compte créé."""
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

    # Sélection des datasets, aucun n'est coché au départ.
    st.write("Datasets autorisés")
    prefixe_dataset = f"ajout_dataset_{fid}_"
    afficher_arborescence_datasets(DATASETS_REMOTE_PATH, prefixe_dataset, [])

    # Le bouton est en dernière position, sous les datasets.
    if not st.button("Créer le compte", type="primary", key=f"ajout_submit_{fid}"):
        return

    new_datasets_access = lire_selection(prefixe_dataset)

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
        # Cas rare : deux clics simultanés ont passé la vérification
        # ci-dessus en même temps, l'index unique en base tranche.
        st.error("Ce nom d'utilisateur existe déjà.")
        return

    st.session_state["ajout_created"] = created
    st.rerun()


# ---------------------------------------------------------------------------
# Mode 2 : import CSV
# ---------------------------------------------------------------------------


def render_import_result(result: dict) -> None:
    """Bilan affiché après un import, avec le nombre de comptes en attente."""
    if result["created_count"]:
        st.success(f"{result['created_count']} compte(s) créé(s).")
    else:
        st.info("Aucun compte n'a été créé.")

    if result["rejected"]:
        st.warning(f"{len(result['rejected'])} ligne(s) rejetée(s) :")
        st.dataframe(result["rejected"], width="stretch", hide_index=True)

    # Comptes créés sans mot de passe : l'admin doit les compléter à la main
    if result["pending_count"]:
        st.warning(
            f"{result['pending_count']} compte(s) sont en attente : ils ne "
            "peuvent pas se connecter tant qu'un mot de passe n'a pas été "
            "défini. Rendez-vous sur la page Comptes utilisateurs, "
            "sélectionnez chaque compte puis utilisez la section Mot de passe."
        )
        st.page_link(
            "pages/3b_comptes_utilisateurs.py",
            label="Aller à la page Comptes utilisateurs",
            icon=":material/group:",
        )

    if st.button("Terminer et faire un nouvel import", type="primary"):
        st.session_state["import_result"] = None
        st.rerun()


def render_add_csv(users) -> None:
    """Import de plusieurs comptes depuis un CSV, avec contrôle avant création."""
    result = st.session_state.get("import_result")
    if result:
        render_import_result(result)
        return

    import_id = st.session_state["import_id"]

    st.write(
        "Créez plusieurs comptes d'un coup à partir d'un fichier CSV. La "
        "colonne password est optionnelle : si elle est vide, le compte est "
        "créé en attente et vous définirez son mot de passe ensuite depuis "
        "la page Comptes utilisateurs. Pensez à supprimer le fichier de "
        "votre poste s'il contient des mots de passe."
    )
    st.download_button(
        "Télécharger le modèle CSV",
        data=build_template_csv(),
        file_name="modele_import_utilisateurs.csv",
        mime="text/csv",
        on_click="ignore",
    )

    # Sélection du fichier CSV : on s'arrête tant qu'aucun fichier n'est chargé
    uploaded = st.file_uploader(
        "Fichier CSV", type=["csv"], key=f"import_uploader_{import_id}"
    )
    if uploaded is None:
        return

    # Lecture du fichier : on affiche l'erreur si le CSV est inutilisable
    try:
        df = parse_csv(uploaded.getvalue())
    except ValueError as exc:
        st.error(str(exc))
        return

    # Aide explicite pour la suppression et l'ajout de lignes
    st.write(
        "Vérifiez le contenu et corrigez-le directement dans le tableau si "
        "besoin. Pour supprimer une ligne, cochez la case à gauche de la "
        "ligne puis cliquez sur la corbeille en haut à droite du tableau "
        "(ou appuyez sur la touche Suppr). Pour ajouter une ligne, "
        "saisissez-la dans la dernière ligne vide."
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

    # Répartition des rôles parmi les lignes valides
    nb_admin = sum(1 for r in valid_rows if r["role"] == "admin")
    nb_user = len(valid_rows) - nb_admin

    # Statistiques de l'import
    col_total, col_ok, col_ko, col_roles = st.columns(4)
    col_total.metric("Total de lignes", len(valid_rows) + len(rejected_rows))
    col_ok.metric("Lignes valides", len(valid_rows))
    col_ko.metric("Lignes à corriger", len(rejected_rows))
    col_roles.metric("Rôles (lignes valides)", f"{nb_user} user / {nb_admin} admin")

    if rejected_rows:
        st.warning(
            "Les lignes à corriger ne seront pas importées tant qu'elles "
            "ne sont pas corrigées dans le tableau ci-dessus."
        )

    # Tableau de contrôle : toutes les lignes avec "OK" ou le motif d'erreur
    st.write("Contrôle des lignes :")
    st.dataframe(
        build_status_table(valid_rows, rejected_rows),
        width="stretch",
        hide_index=True,
    )

    if not valid_rows:
        st.info("Aucune ligne valide à importer pour le moment.")
        return

    if st.button(f"Importer {len(valid_rows)} compte(s)", type="primary"):
        with st.spinner("Création des comptes en cours..."):
            created, failed = create_users_from_rows(users, valid_rows)

        st.session_state["import_result"] = {
            "created_count": len(created),
            # Comptes créés sans mot de passe (à compléter par l'admin)
            "pending_count": sum(1 for c in created if not c["mot_de_passe_defini"]),
            "rejected": rejected_rows + failed,
        }
        # Nouvelle clé pour vider le file_uploader et l'éditeur.
        st.session_state["import_id"] += 1
        st.rerun()


# ---------------------------------------------------------------------------
# Mise en page
# ---------------------------------------------------------------------------

ensure_username_index_once()
users_collection = get_users_collection()

st.title("Ajout d'un utilisateur")

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