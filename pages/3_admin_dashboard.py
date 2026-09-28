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
from modules.datasets import (
    DATASETS_REMOTE_PATH,
    chemin_relatif,
    list_folder_contents,
    mettre_a_jour_selection,
)
from modules.db_mongo import get_users_collection
from ui.flash import flash, render_flash
from ui.topnav import configurer_page, render_topnav
from modules.user_import import (
    ROLES,
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
    is_password_pending,
    reset_password,
    update_user,
    validate_new_password,
    validate_new_user,
    validate_user_update,
)

configurer_page("Espace Admin")

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
# comptes_table_id : compteur qui change la clé du tableau des comptes, ce
# qui efface la ligne sélectionnée (utilisé après une suppression).
st.session_state.setdefault("comptes_table_id", 0)


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
                # Les lignes du tableau ont changé de position : on efface la sélection
                st.session_state["comptes_table_id"] += 1
            else:
                flash("error", "Le compte n'a pas pu être supprimé.", "comptes")
            st.rerun()
    with col_cancel:
        if st.button("Annuler", width="stretch"):
            st.rerun()


# ---------------------------------------------------------------------------
# Affichage des datasets, niveau par niveau (utilise par les deux formulaires)
# ---------------------------------------------------------------------------


def _sur_case_modifiee(cle_selection: str, chemin: str, cle_case: str) -> None:
    """Met à jour la sélection en session quand une case est cochée ou décochée."""
    st.session_state[cle_selection] = mettre_a_jour_selection(
        st.session_state[cle_selection], chemin, st.session_state[cle_case]
    )


def _sur_bouton_dossier(cle_ouverts: str, chemin: str) -> None:
    """Ouvre un dossier s'il est fermé, le ferme sinon."""
    ouverts = st.session_state[cle_ouverts]
    if chemin in ouverts:
        ouverts.remove(chemin)
    else:
        ouverts.add(chemin)


def _retirer_de_la_selection(cle_selection: str, chemin: str) -> None:
    """Retire un chemin de la sélection (bouton Retirer du récapitulatif)."""
    st.session_state[cle_selection] = mettre_a_jour_selection(
        st.session_state[cle_selection], chemin, False
    )


def lire_selection(prefixe_cle: str) -> list:
    """Renvoie la liste triée des chemins cochés pour ce formulaire."""
    return sorted(st.session_state.get(f"{prefixe_cle}selection", set()))


def _colonnes_ligne(profondeur: int):
    """
    Découpe une ligne en un décalage vide, une colonne pour le chevron et
    une colonne pour le contenu. Renvoie (colonne_chevron, colonne_contenu).

    Le total des poids est toujours le même (31) : le décalage d'un niveau
    correspond donc à la largeur d'un chevron, et les éléments d'un dossier
    s'alignent sous le nom de ce dossier.
    """
    profondeur = min(profondeur, 25)
    poids = ([profondeur] if profondeur > 0 else []) + [1, 30 - profondeur]
    colonnes = st.columns(poids, vertical_alignment="center", gap="small")
    return colonnes[-2], colonnes[-1]


def _afficher_niveau(chemin: str, prefixe_cle: str, profondeur: int) -> None:
    """
    Affiche un dossier : une ligne par élément (chevron pour les dossiers,
    case à cocher pour tous). Si un dossier est ouvert, son contenu est
    affiché juste en dessous, décalé d'un cran vers la droite.
    """
    cle_selection = f"{prefixe_cle}selection"
    cle_ouverts = f"{prefixe_cle}ouverts"

    # Un seul niveau est lu sur le serveur à chaque appel
    elements = list_folder_contents(chemin)
    if not elements:
        if profondeur == 0:
            st.info("Aucun dataset trouvé sur le serveur.")
        else:
            _, colonne_contenu = _colonnes_ligne(profondeur)
            colonne_contenu.caption("Dossier vide ou inaccessible.")
        return

    for element in elements:
        chemin_element = element["chemin"]
        cle_case = f"{prefixe_cle}case_{chemin_element}"
        est_ouvert = chemin_element in st.session_state[cle_ouverts]

        # L'état de la case est recalculé à partir de la sélection à chaque
        # affichage : ainsi, retirer un élément depuis le récapitulatif
        # décoche aussi sa case dans la liste.
        st.session_state[cle_case] = chemin_element in st.session_state[cle_selection]

        colonne_chevron, colonne_case = _colonnes_ligne(profondeur)
        with colonne_chevron:
            # Chevron réservé aux dossiers (les fichiers n'ont pas de bouton)
            if element["est_dossier"]:
                st.button(
                    "",
                    key=f"{prefixe_cle}chevron_{chemin_element}",
                    icon=":material/expand_more:" if est_ouvert else ":material/chevron_right:",
                    type="tertiary",
                    help="Replier ce dossier" if est_ouvert else "Déplier ce dossier",
                    on_click=_sur_bouton_dossier,
                    args=(cle_ouverts, chemin_element),
                )
        with colonne_case:
            # Un "/" final distingue les dossiers des fichiers.
            libelle = element["nom"] + ("/" if element["est_dossier"] else "")
            st.checkbox(
                libelle,
                key=cle_case,
                on_change=_sur_case_modifiee,
                args=(cle_selection, chemin_element, cle_case),
            )

        # Contenu du dossier ouvert, un cran plus à droite
        if element["est_dossier"] and est_ouvert:
            _afficher_niveau(chemin_element, prefixe_cle, profondeur + 1)


def afficher_arborescence_datasets(racine: str, prefixe_cle: str,
                                    deja_autorises: list) -> None:
    """
    Affiche les datasets du serveur sous forme d'arborescence à plat : un
    dossier se déplie ou se replie avec son chevron, et son contenu est
    indenté sous lui. Un récapitulatif des éléments sélectionnés (avec un
    bouton pour retirer chacun d'eux) est affiché sous l'arborescence.

    Le contenu d'un dossier n'est lu sur le serveur que lorsqu'il est
    déplié. La sélection et la liste des dossiers dépliés sont mémorisées
    en session (prefixe_cle + "selection" et prefixe_cle + "ouverts"),
    donc replier un dossier ne fait perdre aucune case cochée.
    """
    cle_selection = f"{prefixe_cle}selection"
    st.session_state.setdefault(cle_selection, set(deja_autorises))
    st.session_state.setdefault(f"{prefixe_cle}ouverts", set())

    _afficher_niveau(racine, prefixe_cle, 0)

    # Récapitulatif de la sélection (chemins affichés sans la racine)
    selection = sorted(st.session_state[cle_selection])
    with st.expander(f"Datasets sélectionnés ({len(selection)})", expanded=True):
        if not selection:
            st.caption("Aucun dataset sélectionné.")
        for chemin_selectionne in selection:
            colonne_nom, colonne_retirer = st.columns([8, 1], vertical_alignment="center")
            with colonne_nom:
                st.text(chemin_relatif(racine, chemin_selectionne))
            with colonne_retirer:
                st.button(
                    "Retirer",
                    key=f"{prefixe_cle}retirer_{chemin_selectionne}",
                    on_click=_retirer_de_la_selection,
                    args=(cle_selection, chemin_selectionne),
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
            "défini. Rendez-vous dans l'onglet Comptes utilisateurs, "
            "sélectionnez chaque compte puis utilisez la section Mot de passe."
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
        "Créez plusieurs comptes d'un coup à partir d'un fichier CSV. La "
        "colonne password est optionnelle : si elle est vide, le compte est "
        "créé en attente et vous définirez son mot de passe ensuite depuis "
        "l'onglet Comptes utilisateurs. Pensez à supprimer le fichier de "
        "votre poste s'il contient des mots de passe."
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
            # Comptes créés sans mot de passe (à compléter par l'admin)
            "pending_count": sum(1 for c in created if not c["mot_de_passe_defini"]),
            "rejected": rejected_rows + failed,
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

    # Les cles contiennent l'_id du compte : elles restent stables meme si
    # le username est modifie, et ne se melangent pas d'un compte a l'autre.
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
                    # Si l'admin renomme son propre compte, on met a jour sa
                    # session pour que les controles de suppression restent
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