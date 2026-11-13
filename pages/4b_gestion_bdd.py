"""
Page Gestion des BDD : section de l'espace de travail (rôle user).

Affiche les datasets autorisés pour l'utilisateur connecté, regroupés par
projet (dossier parent). Chaque dataset a sa carte, avec son état et des
statistiques calculées sur le serveur de l'école.
"""

import hashlib
import os

import streamlit as st

from modules.comptes.auth import require_role
from modules.datasets.exploration_dataset import chemin_relatif, get_datasets_autorises
from modules.datasets.sftp import DATASETS_REMOTE_PATH
from modules.datasets.stats import SPLITS, calculer_stats
from modules.datasets.upload import ajouter_dataset, dossier_utilisateur
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


def couleur_split(details: dict):
    """
    Renvoie la couleur d'une ligne du tableau des splits.

    - "red" : le split est absent ou ne contient aucun cube
    - "orange" : il y a des cubes, mais il manque des masques ou des images RGB
    - None : le split est correct (texte sans couleur)
    """
    if details["cubes"] == 0:
        return "red"
    if details["annotes"] < details["cubes"] or details["rgb"] < details["cubes"]:
        return "orange"
    return None


def tableau_splits(details_par_split: dict) -> str:
    """
    Construit le tableau markdown des splits : une ligne par split avec le
    nombre de cubes, de masques et d'images RGB. La ligne est colorée selon
    couleur_split.
    """
    # En-tête du tableau. La deuxième ligne règle l'alignement des colonnes :
    # nom du split à gauche, chiffres centrés
    lignes = ["| Split | Cubes | Masques | RGB |", "|:--|:-:|:-:|:-:|"]

    for nom in SPLITS:
        # Un split absent du résultat compte comme un split vide
        details = details_par_split.get(nom, {"cubes": 0, "annotes": 0, "rgb": 0})
        cellules = [
            nom,
            str(details["cubes"]),
            str(details["annotes"]),
            str(details["rgb"]),
        ]

        # Colorer toute la ligne : on colore chaque cellule
        couleur = couleur_split(details)
        if couleur:
            cellules = [f":{couleur}[{cellule}]" for cellule in cellules]

        lignes.append("| " + " | ".join(cellules) + " |")

    return "\n".join(lignes)


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
    """Affiche la carte d'un dataset : bandeau, encadré de statistiques et menu des tâches."""
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

        # .get() évite une KeyError si le résultat en cache date d'avant
        # l'ajout du détail par split
        details_par_split = stats.get("details_par_split")

        if details_par_split is None:
            st.caption(
                "Statistiques obsolètes. Cliquez sur Rafraîchir les "
                "statistiques pour afficher le détail."
            )
        else:
            # Encadré discret des statistiques : totaux puis tableau par split
            # (deux espaces + retour = saut de ligne)
            with st.container(key=f"stats-{cle}"):
                total = stats["total_cubes"]
                st.markdown(
                    f"Cubes HSI : **{total}**  \n"
                    f"Masques d'annotation : **{stats['annotes']}/{total}**  \n"
                    f"Images RGB : **{stats['rgb']}/{total}**"
                )
                st.markdown(tableau_splits(details_par_split))

        # Menu déroulant "À faire", replié par défaut : le nombre de tâches
        # est dans le titre. .get() évite une KeyError si le résultat en cache
        # date d'avant l'ajout de cette clé.
        taches = stats.get("taches", [])
        if taches:
            with st.expander(f"À faire ({len(taches)})", expanded=False):
                st.markdown("\n".join("- " + tache for tache in taches))


def afficher_projet(parent: str, datasets: list, username: str) -> None:
    """
    Affiche un groupe de datasets : son titre, puis ses cartes par rangées.

    Trois cas pour le titre :
      - dossier personnel de l'utilisateur : "Mes bases importées"
      - racine du serveur (datasets attribués par l'admin) : "Bases attribuées"
      - tout autre dossier : son nom, avec son chemin en dessous
    """
    racine = DATASETS_REMOTE_PATH.rstrip("/")
    parent = parent.rstrip("/")

    if parent == racine:
        st.subheader("Bases attribuées")
    elif parent == dossier_utilisateur(username):
        # Le nom du dossier serait le nom de l'utilisateur : on ne l'affiche pas
        st.subheader("Mes bases importées")
    else:
        st.markdown("#### " + os.path.basename(parent))
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


def afficher_formulaire_ajout(users, username: str) -> None:
    """
    Affiche le formulaire d'ajout d'une base de données (archive zip).

    L'envoi et l'attribution des droits sont gérés par ajouter_dataset
    (modules/datasets/upload.py) : cette fonction ne s'occupe que de l'affichage.
    """
    # Message du dernier ajout réussi : la page est relancée après l'ajout,
    # on le garde donc en session pour l'afficher une fois
    message = st.session_state.pop("message_ajout", None)
    if message:
        st.success(message)

    with st.expander("Ajouter une base de données"):
        st.caption(
            "L'archive zip doit contenir les dossiers Train, Test et Val. "
            "Consultez la page Mode d'emploi pour connaître la structure attendue."
        )

        # Un formulaire : rien n'est envoyé tant que le bouton n'est pas cliqué
        with st.form("formulaire_ajout_bdd"):
            nom = st.text_input(
                "Nom du dataset",
                help="Lettres, chiffres, tirets et underscores uniquement.",
            )
            fichier = st.file_uploader("Archive zip", type=["zip"])
            valide = st.form_submit_button("Envoyer sur le serveur")

        if not valide:
            return

        nom = nom.strip()
        if not nom or fichier is None:
            st.error("Renseignez un nom et choisissez une archive zip.")
            return

        # L'envoi peut être long pour de gros datasets
        with st.spinner("Envoi en cours, cela peut prendre du temps..."):
            succes, message = ajouter_dataset(users, fichier, username, nom)

        if not succes:
            st.error(message)
            return

        # Succès : on vide le cache des statistiques et on relance la page
        # pour afficher la nouvelle carte
        stats_en_cache.clear()
        st.session_state["message_ajout"] = message
        st.rerun()


# Injection du style des cartes (une seule fois par chargement de page)
st.markdown(STYLE_CARTES, unsafe_allow_html=True)

st.title("Gestion des bases de données")

# Nom d'utilisateur de la personne connectée (même clé que dans la page admin)
username = st.session_state.get("username")
users = get_users_collection()

# Le formulaire est affiché AVANT le st.stop() ci-dessous : un utilisateur
# sans aucun dataset doit pouvoir en ajouter un
afficher_formulaire_ajout(users, username)

# Lecture des droits en base à chaque chargement de la page
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


# Dossier personnel de l'utilisateur, affiché en premier
dossier_perso = dossier_utilisateur(username)

with st.spinner("Calcul des statistiques en cours..."):
    # Ordre : dossier personnel d'abord, puis les autres par ordre alphabétique
    # (la clé de tri place False, donc le dossier perso, avant True)
    for parent in sorted(projets, key=lambda p: (p != dossier_perso, p)):
        afficher_projet(parent, projets[parent], username)