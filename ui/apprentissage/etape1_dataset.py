"""Interface de l'étape 1 (Dataset) de la page Apprentissage.

Logique métier dans modules/apprentissage/etape_dataset.py.
"""

import streamlit as st

from modules.apprentissage.formats import formater_splits
from modules.datasets.exploration_dataset import chemin_relatif
from modules.datasets.sftp import DATASETS_REMOTE_PATH
from ui.apprentissage import etat
from ui.apprentissage.cache import datasets_complets, stats_du_dataset
from ui.apprentissage.styles import STYLE_CARTES

# Nombre de cartes par rangée
CARTES_PAR_RANGEE = 3


def afficher_infos(chemin, cle):
    """Affiche le contenu d'une carte : bandeau, cubes, masques, RGB et splits.

    `cle` rend unique la clé du bandeau (une carte par dataset).
    """
    stats = stats_du_dataset(chemin)
    total = stats["total_cubes"]

    # Bandeau d'en-tête : nom à gauche, badge d'état à droite. Tous les
    # datasets proposés sont à l'état Complet : le bandeau est toujours vert.
    with st.container(key=f"entete-green-{cle}"):
        colonne_nom, colonne_badge = st.columns([3, 2], vertical_alignment="center")
        colonne_nom.markdown("**" + chemin_relatif(DATASETS_REMOTE_PATH, chemin) + "**")
        colonne_badge.badge("Complet", color="green")

    # Deux espaces + retour = saut de ligne
    st.markdown(
        f"Cubes : **{total}**  \n"
        f"Masques : **{stats['annotes']}/{total}**  \n"
        f"Images RGB : **{stats['rgb']}/{total}**"
    )
    st.caption("Splits : " + formater_splits(stats["cubes_par_split"]))


def afficher_carte(chemin, index, selectionnee):
    """Affiche la carte d'un dataset avec son bouton de sélection."""
    # La clé du conteneur donne la classe CSS qui met la carte en évidence
    statut = "selectionnee" if selectionnee else "normale"
    with st.container(key=f"carte-{statut}-{index}"):
        afficher_infos(chemin, index)

        # Le bouton de la carte choisie change de libellé et permet de désélectionner
        clic = st.button(
            "Désélectionner" if selectionnee else "Sélectionner",
            key=f"selection_{index}",
            type="primary" if selectionnee else "secondary",
            width="stretch",
        )
        if clic:
            # Un clic sur la carte choisie annule la sélection, sinon il la choisit
            st.session_state[etat.SELECTION] = None if selectionnee else chemin
            # Changer de sélection annule une confirmation en attente
            st.session_state[etat.CONFIRMER_CHANGEMENT] = None
            st.rerun()


def grille_cartes(complets):
    """Affiche les cartes par rangées de CARTES_PAR_RANGEE."""
    selection = st.session_state.get(etat.SELECTION)

    for debut in range(0, len(complets), CARTES_PAR_RANGEE):
        colonnes = st.columns(CARTES_PAR_RANGEE)
        lot = complets[debut:debut + CARTES_PAR_RANGEE]
        # zip s'arrête au plus court : les colonnes en trop restent vides,
        # ce qui garde la même largeur pour toutes les cartes
        for decalage, (colonne, chemin) in enumerate(zip(colonnes, lot)):
            with colonne:
                afficher_carte(chemin, debut + decalage, chemin == selection)


def valider_dataset(chemin):
    """Enregistre le dataset validé et ouvre l'étape suivante.

    Si le dataset change, la version de patches et la configuration sont
    réinitialisées. Valider de nouveau le même dataset ne réinitialise rien.
    """
    if chemin != st.session_state.get(etat.DATASET):
        st.session_state[etat.VERSION] = None
        st.session_state[etat.CONFIG] = None
    st.session_state[etat.DATASET] = chemin
    st.session_state[etat.CONFIRMER_CHANGEMENT] = None
    st.session_state[etat.ETAPE] = 1
    st.rerun()


def demander_confirmation():
    """Affiche l'avertissement de changement de dataset, s'il y en a un en attente."""
    # Contient le chemin du dataset à valider, ou None s'il n'y a rien en attente
    en_attente = st.session_state.get(etat.CONFIRMER_CHANGEMENT)
    if en_attente is None:
        return

    st.warning(
        "Changer de dataset réinitialisera la version de patches choisie "
        "et le paramétrage. Voulez-vous continuer ?"
    )
    col1, col2 = st.columns(2)
    if col1.button("Confirmer le changement", type="primary", width="stretch"):
        valider_dataset(en_attente)
    if col2.button("Annuler", width="stretch"):
        st.session_state[etat.CONFIRMER_CHANGEMENT] = None
        st.rerun()


def etape_dataset():
    """Étape 1 : choix du dataset par cartes (uniquement ceux à l'état Complet)."""
    st.subheader("Choix du dataset")
    st.markdown(STYLE_CARTES, unsafe_allow_html=True)

    st.caption(
        "Seuls les datasets à l'état Complet sont proposés. "
        "Sélectionnez une carte, puis validez."
    )

    with st.spinner("Recherche des datasets complets..."):
        complets = datasets_complets(st.session_state["username"])

    # Aucun dataset disponible : on informe l'utilisateur
    if not complets:
        st.warning(
            "Aucun dataset à l'état Complet n'est disponible pour votre compte. "
            "Rendez-vous dans la page Gestion des BDD pour en compléter un."
        )
        return

    grille_cartes(complets)

    # Choix en cours (None tant qu'aucune carte n'est sélectionnée)
    selection = st.session_state.get(etat.SELECTION)
    if selection is None:
        st.caption("Aucune carte sélectionnée.")
    else:
        st.caption(
            "Dataset sélectionné : " + chemin_relatif(DATASETS_REMOTE_PATH, selection)
        )

    # Validation : changer de dataset alors qu'une version de patches est déjà
    # choisie demande d'abord confirmation (la version serait réinitialisée)
    if st.button("Valider ce dataset", type="primary", disabled=selection is None):
        valide = st.session_state.get(etat.DATASET)
        version = st.session_state.get(etat.VERSION)
        if valide is not None and selection != valide and version is not None:
            st.session_state[etat.CONFIRMER_CHANGEMENT] = selection
        else:
            valider_dataset(selection)

    demander_confirmation()
