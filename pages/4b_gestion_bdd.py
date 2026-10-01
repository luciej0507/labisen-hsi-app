"""
Page Gestion des BDD : section de l'espace de travail (rôle user).

Affiche les datasets autorisés pour l'utilisateur connecté, regroupés par
projet (dossier parent). Chaque dataset a sa carte, avec son état et des
statistiques calculées sur le serveur de l'école.
"""

import hashlib
import os

import streamlit as st

from modules.auth import require_role
from modules.datasets import (
    DATASETS_REMOTE_PATH,
    calculer_stats,
    chemin_relatif,
    etat_split,
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

# Style des cartes. Chaque conteneur créé avec une clé reçoit une classe CSS
# "st-key-<clé>" : on s'en sert pour colorer le bandeau et l'encadré de stats.
# Les couleurs sont semi-transparentes pour rester lisibles en thème clair
# comme en thème sombre.
STYLE_CARTES = """
<style>
/* Bandeau d'en-tête : espacement et coins arrondis */
div[class*="st-key-entete-"] {
    padding: 0.5rem 0.75rem;
    border-radius: 0.5rem;
}
/* Couleur du bandeau selon l'état (mêmes couleurs que les badges) */
div[class*="st-key-entete-green"] { background-color: rgba(33, 195, 84, 0.15); }
div[class*="st-key-entete-orange"] { background-color: rgba(255, 140, 0, 0.15); }
div[class*="st-key-entete-red"] { background-color: rgba(255, 75, 75, 0.15); }
div[class*="st-key-entete-gray"] { background-color: rgba(128, 128, 128, 0.15); }
/* Encadré des statistiques : fond gris très discret */
div[class*="st-key-stats-"] {
    padding: 0.5rem 0.75rem;
    border-radius: 0.5rem;
    background-color: rgba(128, 128, 128, 0.08);
}
</style>
"""


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


def afficher_entete(nom: str, etat: str, cle: str) -> None:
    """
    Affiche le bandeau coloré de la carte : nom du dataset à gauche, badge
    d'état à droite. La couleur du fond suit l'état (voir STYLE_CARTES).
    """
    couleur = COULEURS_ETAT.get(etat, "gray")
    # La clé donne au conteneur une classe CSS "st-key-entete-<couleur>-..."
    with st.container(key=f"entete-{couleur}-{cle}"):
        # Deux colonnes : le nom prend plus de place que le badge
        colonne_nom, colonne_badge = st.columns([3, 2], vertical_alignment="center")
        colonne_nom.markdown("**" + nom + "**")
        colonne_badge.badge(etat, color=couleur)


def afficher_carte(chemin: str) -> None:
    """Affiche la carte d'un dataset : bandeau, encadré de statistiques et tâches."""
    # Le nom du dataset est le dernier morceau du chemin
    nom = os.path.basename(chemin.rstrip("/"))

    # Identifiant court et unique par carte, pour les clés des conteneurs
    cle = hashlib.md5(chemin.encode("utf-8")).hexdigest()[:8]

    with st.container(border=True):
        # Serveur injoignable : message sur cette carte uniquement
        try:
            stats = stats_en_cache(chemin)
        except ConnectionError:
            afficher_entete(nom, "Serveur injoignable", cle)
            st.caption("Serveur injoignable. Cliquez sur Rafraîchir pour réessayer.")
            return

        etat = stats["etat"]
        afficher_entete(nom, etat, cle)

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

        # État du split (Fait, Incomplet ou Non fait), règle définie dans datasets.py
        cubes_par_split = stats["cubes_par_split"]
        etat_du_split = etat_split(cubes_par_split)

        # Détail du nombre de cubes par split, en texte gris
        detail_split = ", ".join(
            f"{nom_split} {nb}" for nom_split, nb in cubes_par_split.items()
        )

        # Encadré discret des statistiques, sur deux colonnes
        # (deux espaces + retour = saut de ligne)
        with st.container(key=f"stats-{cle}"):
            colonne_gauche, colonne_droite = st.columns(2)
            colonne_gauche.markdown(
                f"Cubes HSI : **{stats['total_cubes']}**  \n"
                f"Annotés : **{stats['annotes']}/{stats['total_cubes']}**"
            )
            colonne_droite.markdown(
                f"Split : **{etat_du_split}**  \n"
                f":gray[{detail_split}]"
            )

        # Bloc "À faire" sans fond, en liste à puces. .get() évite une
        # KeyError si le résultat en cache date d'avant l'ajout de cette clé.
        taches = stats.get("taches", [])
        if taches:
            liste = "\n".join("- " + tache for tache in taches)
            st.markdown("**À faire**\n\n" + liste)


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


# Injection du style des cartes (une seule fois par chargement de page)
st.markdown(STYLE_CARTES, unsafe_allow_html=True)

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