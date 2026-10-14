"""
3a_ajout_utilisateur.py : ajout d'utilisateurs (espace administrateur).

Deux modes : création d'un seul compte via un formulaire, ou création
de plusieurs comptes à partir d'un fichier CSV.

Cette page ne contient que de l'affichage Streamlit. La logique métier
(validation, écriture en base) est dans modules/users.py et
modules/user_import.py.
"""

import pandas as pd
import streamlit as st
from pymongo.errors import DuplicateKeyError

from modules.auth import require_role
from modules.datasets import DATASETS_REMOTE_PATH
from modules.db_mongo import get_users_collection
from modules.user_import import (
    ACTION_CREATE,
    ACTION_FIX,
    ACTION_IGNORE,
    ACTION_UPDATE,
    CSV_COLUMNS,
    ROLES,
    STATUS_CREATE,
    STATUS_DUPLICATE,
    STATUS_EMPTY,
    STATUS_EXISTING,
    STATUS_INVALID,
    apply_actions,
    build_template_csv,
    classify_rows,
    parse_csv,
    resolve_action,
)
from modules.users import (
    create_user,
    create_users_from_rows,
    update_users_from_rows,
    validate_new_user,
)
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
# import_lines : lignes de l'import en cours (liste de dicts), modifiées
# quand l'admin édite le tableau.
st.session_state.setdefault("import_lines", [])
# import_next_line : dernier numéro de ligne attribué (pour les lignes ajoutées).
st.session_state.setdefault("import_next_line", 0)
# import_editor_version : change à chaque modification du tableau pour qu'il
# soit réaffiché sans modification en attente.
st.session_state.setdefault("import_editor_version", 0)
# import_file_signature : identifie le fichier chargé (None si aucun).
st.session_state.setdefault("import_file_signature", None)


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


def apply_editor_changes(editor_key: str) -> None:
    """
    Applique à la liste des lignes de l'import les modifications faites
    dans le tableau : cellules modifiées, lignes supprimées ou ajoutées.

    Appelée par Streamlit avant le rerun. Le tableau est ensuite réaffiché
    avec les statuts recalculés, et sa clé change pour repartir sans
    modification en attente.
    """
    changes = st.session_state[editor_key]
    lines = st.session_state["import_lines"]

    # Cellules modifiées : les clés sont les positions des lignes affichées
    for position, values in changes["edited_rows"].items():
        for column, value in values.items():
            lines[int(position)][column] = (value or "").strip()

    # Lignes supprimées : de la fin vers le début pour garder les positions
    for position in sorted(changes["deleted_rows"], reverse=True):
        del lines[int(position)]

    # Lignes ajoutées : nouveau numéro de ligne, champs non remplis vides
    for new_row in changes["added_rows"]:
        st.session_state["import_next_line"] += 1
        line = {"ligne": st.session_state["import_next_line"]}
        for column in CSV_COLUMNS + ["action"]:
            line[column] = (new_row.get(column) or "").strip()
        lines.append(line)

    st.session_state["import_editor_version"] += 1


def render_import_result(result: dict) -> None:
    """Bilan affiché après un import : créés, mis à jour, ignorés, rejetés."""
    if result["created_count"]:
        st.success(f"{result['created_count']} compte(s) créé(s).")
    if result["updated_count"]:
        st.success(f"{result['updated_count']} compte(s) mis à jour.")
    if not result["created_count"] and not result["updated_count"]:
        st.info("Aucun compte n'a été créé ni mis à jour.")
    if result["ignored_count"]:
        st.info(f"{result['ignored_count']} ligne(s) ignorée(s).")

    if result["rejected"]:
        st.warning(f"{len(result['rejected'])} ligne(s) rejetée(s) :")
        st.dataframe(result["rejected"], width="stretch", hide_index=True)

    # Les comptes créés n'ont ni mot de passe ni dataset : l'admin les complète
    if result["created_count"]:
        st.warning(
            f"{result['created_count']} compte(s) créé(s) sont en attente : "
            "ils ne peuvent pas se connecter tant qu'un mot de passe n'a pas "
            "été défini, et aucun dataset ne leur est encore autorisé. "
            "Rendez-vous sur la page Comptes utilisateurs, sélectionnez "
            "chaque compte puis définissez son mot de passe et ses datasets."
        )

    if st.button("Terminer et faire un nouvel import", type="primary"):
        st.session_state["import_result"] = None
        st.rerun()


# Teintes de fond des cartes : mêmes couleurs que la colonne Statut du
# tableau (STATUS_BACKGROUNDS), semi-transparentes pour rester lisibles en
# thème clair comme en thème sombre.
COUNTER_BACKGROUNDS = {
    "green": "rgba(46, 160, 67, 0.25)",
    "orange": "rgba(255, 165, 0, 0.25)",
    "red": "rgba(220, 53, 69, 0.25)",
}


def render_counter(column, label: str, value: int, color: str = "") -> None:
    """
    Carte avec un grand chiffre sur un fond légèrement teinté. La carte
    n'est teintée que si le chiffre est supérieur à 0 : un compteur d'erreurs
    à 0 ne doit pas ressembler à une alerte. Le texte garde la couleur du
    thème (noir en thème clair, blanc en thème sombre).

    Le style est écrit directement dans le bloc HTML (pas de dépendance aux
    classes internes de Streamlit). Le contenu est fixe : un libellé et un
    nombre calculés par l'application, jamais du texte saisi par l'admin.
    """
    background = COUNTER_BACKGROUNDS.get(color, "transparent") if value > 0 else "transparent"
    with column:
        st.markdown(
            f'<div style="background-color: {background}; '
            "border: 1px solid rgba(128, 128, 128, 0.35); "
            'border-radius: 0.5rem; padding: 0.75rem 1rem;">'
            f'<div style="font-size: 0.875rem; opacity: 0.8;">{label}</div>'
            f'<div style="font-size: 2.25rem; font-weight: 600; line-height: 1.3;">{value}</div>'
            "</div>",
            unsafe_allow_html=True,
        )


# Couleur de fond de la cellule Statut selon le statut de la ligne. Les
# fonds sont semi-transparents pour rester lisibles en thème clair et sombre.
STATUS_BACKGROUNDS = {
    STATUS_CREATE: "background-color: rgba(46, 160, 67, 0.25)",
    STATUS_EXISTING: "background-color: rgba(255, 165, 0, 0.25)",
    STATUS_DUPLICATE: "background-color: rgba(220, 53, 69, 0.25)",
    STATUS_INVALID: "background-color: rgba(220, 53, 69, 0.25)",
}


def render_add_csv(users) -> None:
    """Import de plusieurs comptes depuis un CSV, avec contrôle avant création."""
    result = st.session_state.get("import_result")
    if result:
        render_import_result(result)
        return

    import_id = st.session_state["import_id"]

    st.write(
        "Créez plusieurs comptes d'un coup à partir d'un fichier CSV. \n\n"
        "Les comptes créés ont tous le rôle utilisateur et sont en attente : vous définirez ensuite leur mot de "
        "passe et leurs datasets depuis la page Comptes utilisateurs."
    )
    st.download_button(
        "Télécharger le modèle CSV",
        data=build_template_csv(),
        file_name="modele_import_utilisateurs.csv",
        mime="text/csv",
        on_click="ignore",
    )

    # Explication du format attendu, repliée par défaut pour alléger la page
    with st.expander("Comment remplir le fichier CSV ?"):
        st.markdown(
            "**Colonnes du fichier** : `nom`, `prenom`, `email`, `username`.\n\n"
            "- `nom`, `prenom` et `username` sont obligatoires.\n"
            "- `email` est optionnel, mais il doit être unique : il ne peut "
            "pas être utilisé par un autre compte.\n"
            "- Les colonnes supplémentaires éventuelles sont ignorées.\n"
            "- **Format de l'identifiant conseillé (`username`)** : première lettre du "
            "prénom suivie du nom de famille en entier, en minuscules, sans "
            "accent, sans espace ni tiret. Par exemple, Marie Dupont donne "
            "`mdupont`.\n\n"
            "**Exemples de lignes refusées (à corriger dans le tableau récapitulatif)**\n\n"
            "| nom | prenom | email | username | motif |\n"
            "|---|---|---|---|---|\n"
            "| Dupont | Marie | marie,dupont@exemple.fr | mdupont | email avec une virgule |\n"
            "| Dupont | Marie | marie.dupont@exemple | mdupont | email sans point après le @ |\n"
            "| Dupont | | marie.dupont@exemple.fr | mdupont | prénom manquant |\n"
            "| Dupont | Marie | marie.dupont@exemple.fr | | identifiant manquant |\n\n"
        )

    # Sélection du fichier CSV : on s'arrête tant qu'aucun fichier n'est chargé
    uploaded = st.file_uploader(
        "Fichier CSV", type=["csv"], key=f"import_uploader_{import_id}"
    )
    if uploaded is None:
        # Fichier retiré : le prochain fichier chargé repartira de zéro
        st.session_state["import_file_signature"] = None
        return

    # Lecture du fichier : on affiche l'erreur si le CSV est inutilisable
    try:
        df = parse_csv(uploaded.getvalue())
    except ValueError as exc:
        st.error(str(exc))
        return

    # Nouveau fichier : on remplit la liste des lignes de l'import. Elle est
    # ensuite modifiée par apply_editor_changes quand l'admin édite le tableau.
    file_signature = f"{import_id}_{uploaded.name}_{uploaded.size}"
    if st.session_state["import_file_signature"] != file_signature:
        lines = []
        for line, row in df.iterrows():
            entry = {col: row[col] for col in CSV_COLUMNS}
            entry["ligne"] = int(line)
            # Action vide : l'action par défaut du statut s'applique
            entry["action"] = ""
            lines.append(entry)
        st.session_state["import_lines"] = lines
        st.session_state["import_next_line"] = len(df)
        st.session_state["import_editor_version"] = 0
        st.session_state["import_file_signature"] = file_signature

    lines = st.session_state["import_lines"]

    # Analyse des lignes : statut de chacune (nouveau, existant, doublon...).
    # Les comptes déjà en base (username et email) servent à détecter les conflits.
    lines_df = pd.DataFrame(
        [{col: r[col] for col in CSV_COLUMNS} for r in lines],
        index=[r["ligne"] for r in lines],
        columns=CSV_COLUMNS,
    )
    existing_users = list(users.find({}, {"username": 1, "email": 1}))
    rows = classify_rows(lines_df, existing_users)

    # Actions choisies par l'admin (sans choix, l'action par défaut s'applique)
    chosen_actions = {r["ligne"]: r["action"] for r in lines if r["action"]}
    to_create, to_update, ignored, to_fix = apply_actions(rows, chosen_actions)

    # Statistiques de l'import (les lignes vides ne comptent pas)
    nb_total = sum(1 for r in rows if r["statut"] != STATUS_EMPTY)
    nb_create = sum(1 for r in rows if r["statut"] == STATUS_CREATE)
    nb_existing = sum(1 for r in rows if r["statut"] == STATUS_EXISTING)
    nb_problem = sum(
        1 for r in rows if r["statut"] in (STATUS_DUPLICATE, STATUS_INVALID)
    )
    col_total, col_new, col_existing, col_ko = st.columns(4)
    render_counter(col_total, "Total de lignes", nb_total)
    render_counter(col_new, "Nouveaux comptes", nb_create, "green")
    render_counter(col_existing, "Comptes existants", nb_existing, "orange")
    render_counter(col_ko, "Doublons ou erreurs", nb_problem, "red")

    st.write(
        "Vérifiez les comptes et corrigez-les directement dans le tableau. "
        "Le statut se met à jour après chaque modification, et l'action de "
        "chaque ligne se choisit dans la dernière colonne.\n"
        "- Pour supprimer une ligne, cochez la case à gauche de la ligne "
        "puis cliquez sur la corbeille en haut à droite du tableau "
        "(ou appuyez sur la touche Suppr).\n"
        "- Pour ajouter une ligne, saisissez-la dans la dernière ligne vide."
    )

    # Tableau unique : ligne et statut calculés (lecture seule), action et
    # champs du compte modifiables. L'index reste simple (0, 1, 2...) : avec un
    # index personnalisé, Streamlit attend une valeur d'index pour chaque ligne
    # ajoutée et ignore la ligne tant qu'elle n'est pas saisie. Le numéro de
    # ligne est donc une colonne comme les autres.
    table = pd.DataFrame(
        [
            {
                "ligne": r["ligne"],
                "statut": r["motif"],
                "action": resolve_action(r["statut"], chosen_actions.get(r["ligne"])),
                "nom": r["nom"],
                "prenom": r["prenom"],
                "email": r["email"] or "",
                "username": r["username"],
            }
            for r in rows
        ],
        columns=["ligne", "statut", "action", "nom", "prenom", "email", "username"],
    )
    # Couleur de la colonne Statut, ligne par ligne. Les styles pandas ne
    # s'appliquent qu'aux colonnes non modifiables, donc pas aux autres.
    status_styles = [STATUS_BACKGROUNDS.get(r["statut"], "") for r in rows]
    styled_table = table.style.apply(lambda column: status_styles, subset=["statut"])

    editor_key = f"import_editor_{import_id}_{st.session_state['import_editor_version']}"
    st.data_editor(
        styled_table,
        num_rows="dynamic",
        width="stretch",
        hide_index=True,
        # Données du compte à gauche, colonnes de contrôle à droite
        column_order=["ligne", "nom", "prenom", "email", "username", "statut", "action"],
        disabled=["ligne", "statut"],
        column_config={
            "ligne": "Ligne",
            "nom": "Nom",
            "prenom": "Prénom",
            "email": "Email",
            "username": "Identifiant",
            "statut": st.column_config.TextColumn(
                "Statut (automatique)",
                help="Calculé par l'application : indique ce qui va se passer "
                "pour la ligne ou ce qu'il faut corriger.",
            ),
            "action": st.column_config.SelectboxColumn(
                "Action (à choisir)",
                help="Choisissez ce qu'il faut faire de la ligne. Une action "
                "impossible est remplacée par l'action par défaut.",
                options=[ACTION_CREATE, ACTION_UPDATE, ACTION_IGNORE, ACTION_FIX],
            ),
        },
        key=editor_key,
        on_change=apply_editor_changes,
        args=(editor_key,),
    )

    # Légende des couleurs de la colonne Statut
    st.caption(
        "Statut : :green[vert] = nouveau compte, :orange[orange] = compte "
        "existant (à ignorer ou mettre à jour), :red[rouge] = doublon ou "
        "erreur à corriger."
    )

    if to_fix:
        st.warning(
            f"{len(to_fix)} ligne(s) ne seront pas importées tant "
            "qu'elles ne sont pas corrigées dans le tableau ci-dessus."
        )

    if not to_create and not to_update:
        st.info("Aucune ligne à importer pour le moment.")
        return

    if st.button(
        f"Valider l'import ({len(to_create)} création(s), "
        f"{len(to_update)} mise(s) à jour)",
        type="primary",
    ):
        with st.spinner("Import en cours..."):
            created, failed_create = create_users_from_rows(users, to_create)
            updated, failed_update = update_users_from_rows(users, to_update)

        # Lignes rejetées : à corriger, ou refusées par la base à l'écriture
        rejected = [
            {"ligne": r["ligne"], "username": r["username"], "motif": r["motif"]}
            for r in to_fix
        ]
        st.session_state["import_result"] = {
            "created_count": len(created),
            "updated_count": len(updated),
            "ignored_count": len(ignored),
            "rejected": rejected + failed_create + failed_update,
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