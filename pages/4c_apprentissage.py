"""
Page Apprentissage : section de l'espace de travail (rôle user).

Parcours en 4 étapes affiché sous forme de frise : Dataset, Patching,
Entraînement, Récapitulatif. Cette page ne contient que de l'interface.
La logique (étapes, verrouillage, lecture des datasets, patching) est dans
modules/apprentissage.py.
"""

import pandas as pd
import streamlit as st

from modules.apprentissage import (
    CHOIX_N_LINES,
    CHOIX_PATCH_SIZE,
    CHOIX_STRIDE_COLS,
    CHOIX_STRIDE_LINES,
    ETAPES,
    apercu_patching,
    construire_parametres,
    cubes_a_patcher,
    etape_accessible,
    etapes_validees,
    formater_nombre,
    formater_splits,
    lancer_patching_cube,
    largeur_commune,
    libelle_etape,
    libelles_versions,
    lignes_versions,
    lire_dimensions_dataset,
    lire_versions,
    lister_datasets_complets,
    nom_dossier_format,
    options_split_source,
    resume_dataset,
    splits_a_patcher,
    splits_deja_patches,
    splits_restants,
    trouver_version,
    version_utilisable,
)
from modules.auth import require_role
from modules.datasets import DATASETS_REMOTE_PATH, chemin_relatif
from modules.db_mongo import get_users_collection
from ui.sidebar import render_sidebar
from ui.topnav import configurer_page, render_topnav

# Durée (en secondes) pendant laquelle les lectures sur le serveur sont gardées
DUREE_CACHE = 60

# Couleurs des boutons de la frise pour une étape validée
VERT = "#2e9e5b"
VERT_FONCE = "#1b6b3a"


# ---------------------------------------------------------------------------
# Lectures mises en cache (évitent de relire le serveur à chaque clic)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=DUREE_CACHE, show_spinner=False)
def datasets_complets(username):
    """Retourne les chemins des datasets autorisés dont l'état est Complet."""
    return lister_datasets_complets(get_users_collection(), username)


@st.cache_data(ttl=DUREE_CACHE, show_spinner=False)
def resume_du_dataset(chemin_dataset):
    """Retourne le résumé d'un dataset (cubes, annotés, cubes par split)."""
    return resume_dataset(chemin_dataset)


@st.cache_data(ttl=DUREE_CACHE, show_spinner=False)
def versions_du_dataset(chemin_dataset):
    """Retourne les versions préparées d'un dataset, ou None si serveur injoignable."""
    return lire_versions(chemin_dataset)


@st.cache_data(ttl=DUREE_CACHE, show_spinner=False)
def dimensions_du_dataset(chemin_dataset):
    """Retourne les dimensions de tous les cubes du dataset, par split."""
    return lire_dimensions_dataset(chemin_dataset)


# ---------------------------------------------------------------------------
# Frise
# ---------------------------------------------------------------------------

def css_etapes_validees(validees):
    """Construit le CSS qui colore en vert les boutons des étapes validées.

    Streamlit ne propose pas de bouton vert : on cible chaque bouton par sa
    clé (classe st-key-frise_N). Une étape validée ET active reçoit en plus
    une bordure plus marquée pour se distinguer des autres étapes vertes.
    """
    regles = ""
    for index, validee in enumerate(validees):
        if not validee:
            continue
        actif = st.session_state["appr_etape"] == index
        bordure = f"3px solid {VERT_FONCE}" if actif else f"1px solid {VERT}"
        regles += (
            f".st-key-frise_{index} button {{"
            f" background-color: {VERT}; color: white; border: {bordure}; }}"
            f".st-key-frise_{index} button:hover {{"
            f" background-color: {VERT_FONCE}; color: white; }}"
        )
    return regles


def frise(validees):
    """Affiche la frise : un bouton par étape, sur une seule ligne.

    L'étape active est en couleur, une étape validée est en vert. Une étape
    est désactivée tant que les étapes précédentes ne sont pas validées.
    """
    # Injection du CSS des étapes validées (rien à injecter sinon)
    css = css_etapes_validees(validees)
    if css:
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

    colonnes = st.columns(len(ETAPES))
    for index, colonne in enumerate(colonnes):
        actif = st.session_state["appr_etape"] == index
        clic = colonne.button(
            libelle_etape(index, validees[index]),
            key=f"frise_{index}",
            type="primary" if actif else "secondary",
            disabled=not etape_accessible(index, validees),
            width="stretch",
        )
        # Clic sur une étape : on la rend active et on recharge la page
        if clic:
            st.session_state["appr_etape"] = index
            st.rerun()


# ---------------------------------------------------------------------------
# Étape 1 : choix du dataset
# ---------------------------------------------------------------------------

def etape_dataset():
    """Étape 1 : choix du dataset (uniquement ceux à l'état Complet)."""
    st.subheader("Choix du dataset")
    st.caption("Seuls les datasets à l'état Complet sont proposés.")

    with st.spinner("Recherche des datasets complets..."):
        complets = datasets_complets(st.session_state["username"])

    # Aucun dataset disponible : on informe l'utilisateur
    if not complets:
        st.warning(
            "Aucun dataset à l'état Complet n'est disponible pour votre compte. "
            "Rendez-vous dans la page Gestion des BDD pour en compléter un."
        )
        return

    # Si un dataset a déjà été validé, on le présélectionne
    precedent = st.session_state.get("appr_dataset")
    index = complets.index(precedent) if precedent in complets else 0

    choix = st.selectbox(
        "Dataset",
        complets,
        index=index,
        format_func=lambda c: chemin_relatif(DATASETS_REMOTE_PATH, c),
    )

    # Récapitulatif du dataset choisi
    resume = resume_du_dataset(choix)
    col1, col2, col3 = st.columns(3)
    col1.metric("Cubes", resume["total_cubes"])
    col2.metric("Cubes annotés", resume["annotes"])
    col3.metric("Cubes par split", formater_splits(resume["cubes_par_split"]))

    # La validation enregistre le dataset et ouvre l'étape suivante
    if st.button("Valider ce dataset", type="primary"):
        # Changer de dataset invalide la version de patches choisie
        if choix != precedent:
            st.session_state["appr_version"] = None
        st.session_state["appr_dataset"] = choix
        st.session_state["appr_etape"] = 1
        st.rerun()


# ---------------------------------------------------------------------------
# Étape 2 : patching
# ---------------------------------------------------------------------------

def choisir_valeur(label, options, aide, desactive=False):
    """Affiche une rangée de boutons (pills) et retourne la valeur choisie.

    Si l'utilisateur désélectionne le bouton actif, st.pills renvoie None :
    on revient alors à la première valeur de la liste.
    """
    choix = st.pills(
        label,
        options,
        default=options[0],
        selection_mode="single",
        help=aide,
        disabled=desactive,
    )
    return options[0] if choix is None else choix


def section_versions_existantes(versions):
    """Affiche les versions déjà préparées et permet d'en choisir une."""
    if not versions:
        st.info("Aucune version préparée pour ce dataset. Créez-en une ci-dessous.")
        return

    st.markdown(f"**Versions déjà préparées ({len(versions)})**")
    st.dataframe(pd.DataFrame(lignes_versions(versions)), hide_index=True, width="stretch")

    # Présélection de la version déjà choisie, s'il y en a une
    libelles = libelles_versions(versions)
    noms = list(libelles)
    precedente = st.session_state.get("appr_version")
    index = noms.index(precedente) if precedente in noms else 0

    nom = st.selectbox(
        "Version à utiliser", noms, index=index, format_func=libelles.get
    )

    # Sans le split Train, la version ne peut pas servir à l'entraînement
    utilisable = version_utilisable(trouver_version(versions, nom))
    if not utilisable:
        st.caption(
            "Le split Train n'est pas encore patché pour cette version : "
            "elle ne peut pas servir à l'entraînement. Complétez-la ci-dessous."
        )
    if st.button("Utiliser cette version", type="primary", disabled=not utilisable):
        st.session_state["appr_version"] = nom
        st.session_state["appr_etape"] = 2
        st.rerun()


def section_nouvelle_version(chemin_dataset, versions):
    """Permet de créer une version : format, splits restants, aperçu, lancement."""
    # Repliée quand des versions existent déjà, dépliée sinon
    with st.expander("Créer une nouvelle version", expanded=not versions):
        # Format des patches : une rangée de boutons par paramètre
        full_width = st.toggle("Largeur complète (full_width)", value=False)
        n_lines = choisir_valeur(
            "Nombre de lignes (w)", CHOIX_N_LINES, "Largeur de chaque patch."
        )
        patch_size = choisir_valeur(
            "Taille du patch (h)",
            CHOIX_PATCH_SIZE,
            "Taille de chaque patch en colonnes. Désactivé en largeur complète.",
            desactive=full_width,
        )
        stride_lines = choisir_valeur(
            "Stride lignes (sl)",
            CHOIX_STRIDE_LINES,
            "Décalage, en lignes, entre deux patches consécutifs.",
        )
        stride_cols = choisir_valeur(
            "Stride colonnes (sc)",
            CHOIX_STRIDE_COLS,
            "Décalage, en colonnes, entre deux patches consécutifs. "
            "Désactivé en largeur complète.",
            desactive=full_width,
        )

        # Dimensions de tous les cubes, lues une seule fois pour le dataset
        with st.spinner("Lecture des dimensions des cubes..."):
            dimensions = dimensions_du_dataset(chemin_dataset)

        # En largeur complète, le nom du format contient la largeur des cubes
        largeur = None
        if full_width:
            largeur, probleme = largeur_commune(dimensions)
            if probleme:
                st.warning(probleme)
                return

        parametres = construire_parametres(
            n_lines, patch_size, stride_lines, stride_cols, full_width
        )
        nom_dossier = nom_dossier_format(
            n_lines, patch_size, stride_lines, stride_cols, full_width, largeur
        )
        st.write("Nom du dossier généré :")
        st.code(nom_dossier, language=None)

        # Un format déjà patché n'est pas proposé une seconde fois
        restants = splits_restants(versions, nom_dossier)
        if not restants:
            st.info(
                "Ce format est déjà entièrement patché pour ce dataset. "
                "Choisissez-le dans les versions déjà préparées ci-dessus."
            )
            return
        deja = splits_deja_patches(restants)
        if deja:
            st.info(
                f"Déjà patchés pour ce format : {', '.join(deja)}. "
                "Seuls les splits restants sont proposés."
            )

        # Split source : un seul split, ou tous ceux qui restent
        choix_split = st.radio(
            "Split source", options_split_source(restants), horizontal=True
        )
        splits = splits_a_patcher(choix_split, restants)

        apercu = section_apercu(dimensions, splits, parametres)
        section_lancement(chemin_dataset, dimensions, splits, parametres, nom_dossier, apercu)


def section_apercu(dimensions, splits, parametres):
    """Affiche le nombre de cubes et de patches estimés. Retourne l'aperçu."""
    apercu = apercu_patching(dimensions, splits, parametres)

    col1, col2 = st.columns(2)
    col1.metric("Cubes à patcher", apercu["nb_cubes"])
    col2.metric("Patches estimés", formater_nombre(apercu["total_patches"]))

    if apercu["nb_cubes"] == 0:
        st.info("Aucun cube trouvé dans le ou les splits choisis (ou serveur injoignable).")
    else:
        st.caption("Par split : " + formater_splits(apercu["patches_par_split"]))
    if apercu["illisibles"]:
        st.warning(
            f"{apercu['illisibles']} cube(s) aux dimensions illisibles : "
            "ils ne sont pas comptés dans l'estimation."
        )
    return apercu


def section_lancement(chemin_dataset, dimensions, splits, parametres, nom_dossier, apercu):
    """Lance le patching avec une barre de progression."""
    # Le bouton est désactivé tant qu'il n'y a aucun cube à patcher
    if not st.button(
        "Lancer le patching", type="primary", disabled=apercu["nb_cubes"] == 0
    ):
        return

    cubes = cubes_a_patcher(dimensions, splits)
    barre = st.progress(0.0)
    with st.status("Patching en cours...", expanded=True) as statut:
        for i, (split, cube) in enumerate(cubes, start=1):
            st.write(f"Traitement de {cube} (split {split})")
            lancer_patching_cube(chemin_dataset, split, cube, parametres)
            barre.progress(i / len(cubes))
        statut.update(label="Patching terminé", state="complete")

    # La liste des versions doit être relue : la nouvelle version y apparaît,
    # et c'est à l'utilisateur de la choisir ensuite
    versions_du_dataset.clear()
    st.session_state["appr_message"] = (
        f"Patching terminé : {len(cubes)} cube(s) traité(s), format {nom_dossier}. "
        "Choisissez la version dans la liste des versions déjà préparées."
    )
    st.rerun()


def etape_patching():
    """Étape 2 : versions déjà préparées, ou création d'une nouvelle version."""
    st.subheader("Patching")
    st.caption(
        "Les cubes doivent être découpés en patches avant l'entraînement. "
        "Utilisez une version déjà préparée ou créez-en une nouvelle."
    )

    chemin_dataset = st.session_state["appr_dataset"]
    with st.spinner("Recherche des versions déjà préparées..."):
        versions = versions_du_dataset(chemin_dataset)

    # Serveur injoignable : on ne peut ni lister ni créer de version
    if versions is None:
        st.warning("Serveur injoignable : impossible de lire les versions déjà préparées.")
        return

    section_versions_existantes(versions)
    section_nouvelle_version(chemin_dataset, versions)


# ---------------------------------------------------------------------------
# Étapes à venir
# ---------------------------------------------------------------------------

def etape_a_venir(titre):
    """Étapes pas encore développées : simple message."""
    st.subheader(titre)
    st.info("Prochainement")


# ---------------------------------------------------------------------------
# Page principale
# ---------------------------------------------------------------------------

def main():
    """Assemble l'en-tête commun, la frise et l'étape active."""
    # Configuration de la page (doit être la première commande Streamlit).
    configurer_page("Apprentissage")

    # En-tête, contrôle d'accès (rôle user) et menu latéral.
    render_topnav("Mon Espace")
    require_role("user")
    render_sidebar("Apprentissage")

    st.title("Apprentissage")
    st.write("Suivez les étapes pour entraîner un modèle sur vos cubes HSI.")

    # État du parcours : étape active, dataset et version de patches choisis
    st.session_state.setdefault("appr_etape", 0)
    st.session_state.setdefault("appr_dataset", None)
    st.session_state.setdefault("appr_version", None)

    validees = etapes_validees(
        st.session_state["appr_dataset"], st.session_state["appr_version"]
    )
    frise(validees)
    st.divider()

    # Message laissé par l'action précédente (affiché une seule fois)
    message = st.session_state.pop("appr_message", None)
    if message:
        st.success(message)

    # Affichage de l'étape active
    etape = st.session_state["appr_etape"]
    if etape == 0:
        etape_dataset()
    elif etape == 1:
        etape_patching()
    else:
        etape_a_venir(ETAPES[etape]["titre"])


main()