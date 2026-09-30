"""
Page Gestion des BDD : section de l'espace de travail (rôle user).

Affiche les datasets autorisés pour l'utilisateur connecté, regroupés par
projet (dossier parent). Chaque dataset a sa carte, avec son état et des
statistiques calculées sur le serveur de l'école.
"""

import os

import streamlit as st

from modules.auth import require_role
from modules.datasets import (
    DATASETS_REMOTE_PATH,
    SPLITS,
    calculer_stats,
    chemin_relatif,
    get_datasets_autorises,
)
from modules.db_mongo import get_users_collection
from ui.sidebar import render_sidebar
from ui.topnav import configurer_page, render_topnav

configurer_page("Gestion des BDD")

render_topnav("Mon Espace")
require_role("user")
render_sidebar("Gestion des BDD")

# Nombre de cartes par rangée
CARTES_PAR_RANGEE = 3

# Couleur du badge d'état affiché sur chaque carte
COULEURS_ETAT = {
    "Complet": "green",
    "À compléter": "orange",
    "Non conforme": "red",
    "Introuvable": "red",
    "Serveur injoignable": "red",
}


@st.cache_data(ttl=300, show_spinner=False)
def stats_en_cache(chemin: str) -> dict:
    """
    Enveloppe Streamlit autour de calculer_stats : le résultat est gardé
    5 minutes, pour ne pas interroger le serveur à chaque interaction.

    Si le serveur est injoignable, on lève une exception : Streamlit ne met
    pas en cache une exception, donc l'erreur ne reste pas affichée 5 minutes.
    """
    stats = calculer_stats(chemin)
    if stats["etat"] == "Serveur injoignable":
        raise ConnectionError("Serveur injoignable")
    return stats


def afficher_carte(chemin: str) -> None:
    """Affiche la carte compacte d'un dataset : nom, état et statistiques."""
    with st.container(border=True):
        # Le nom du dataset est le dernier morceau du chemin
        st.markdown("**" + os.path.basename(chemin.rstrip("/")) + "**")

        # Serveur injoignable : message sur cette carte uniquement
        try:
            stats = stats_en_cache(chemin)
        except ConnectionError:
            st.badge("Serveur injoignable", color="red")
            st.caption("Serveur injoignable. Cliquez sur Rafraîchir pour réessayer.")
            return

        etat = stats["etat"]
        st.badge(etat, color=COULEURS_ETAT.get(etat, "gray"))

        # Cas où il n'y a aucune statistique à afficher
        if etat == "Introuvable":
            st.caption(
                "Ce chemin n'est pas un dossier accessible : il a peut-être "
                "été renommé, déplacé ou supprimé."
            )
            return
        if etat == "Non conforme":
            st.caption(
                "Aucun dossier Train, Test ou Val trouvé. Consultez la page "
                "Mode d'emploi pour connaître la structure attendue."
            )
            return

        # Le split est fait si les 3 dossiers existent et contiennent des cubes
        cubes_par_split = stats["cubes_par_split"]
        split_fait = len(cubes_par_split) == len(SPLITS) and all(
            nb > 0 for nb in cubes_par_split.values()
        )

        # Statistiques en texte court, une par ligne (deux espaces = retour à la ligne)
        st.markdown(
            f"Cubes HSI : **{stats['total_cubes']}**  \n"
            f"Annotés : **{stats['annotes']}/{stats['total_cubes']}**  \n"
            f"Split : **{'Fait' if split_fait else 'Non fait'}**"
        )

        # Détail du nombre de cubes par split
        st.caption(
            ", ".join(f"{nom} : {nb}" for nom, nb in cubes_par_split.items())
        )

        # Tout ce qui reste à faire pour que le dataset soit complet, une ligne
        # par tâche. .get() évite une KeyError si le résultat en cache date
        # d'avant l'ajout de cette clé : la carte s'affiche alors sans tâches.
        for tache in stats.get("taches", []):
            st.caption("À faire : " + tache)


def afficher_projet(parent: str, datasets: list) -> None:
    """Affiche un projet : son titre, son chemin, puis ses cartes par rangées."""
    est_racine = parent.rstrip("/") == DATASETS_REMOTE_PATH.rstrip("/")

    # Titre : nom du dossier parent (ou un libellé pour la racine du serveur)
    if est_racine:
        st.subheader("Racine du serveur")
    else:
        st.subheader(os.path.basename(parent.rstrip("/")))
        # Chemin complet du projet (relatif à la racine) pour lever toute ambiguïté
        st.caption(chemin_relatif(DATASETS_REMOTE_PATH, parent))

    # Une rangée de 3 colonnes à la fois : on passe à la suivante quand elle est pleine
    for debut in range(0, len(datasets), CARTES_PAR_RANGEE):
        colonnes = st.columns(CARTES_PAR_RANGEE)
        lot = datasets[debut:debut + CARTES_PAR_RANGEE]
        # zip s'arrête au plus court : les colonnes en trop restent vides,
        # ce qui garde la même largeur pour toutes les cartes
        for colonne, chemin in zip(colonnes, lot):
            with colonne:
                afficher_carte(chemin)


st.title("Gestion des bases de données")

# Nom d'utilisateur de la personne connectée (même clé que dans la page admin)
username = st.session_state.get("username")

# Lecture des droits en base à chaque chargement de la page
users = get_users_collection()
chemins = get_datasets_autorises(users, username)

if not chemins:
    st.info("Aucun dataset ne vous a été attribué pour le moment.")
    st.stop()

# Vider le cache force le recalcul des statistiques juste après
if st.button("Rafraîchir les statistiques"):
    stats_en_cache.clear()

# Regroupement des datasets par projet (dossier parent), sur le chemin complet
# pour que deux projets de même nom situés ailleurs restent séparés
projets = {}
for chemin in sorted(chemins):
    parent = os.path.dirname(chemin.rstrip("/"))
    projets.setdefault(parent, []).append(chemin)

with st.spinner("Calcul des statistiques en cours..."):
    # Projets par ordre alphabétique de chemin
    for parent in sorted(projets):
        afficher_projet(parent, projets[parent])