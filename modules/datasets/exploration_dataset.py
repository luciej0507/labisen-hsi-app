"""
modules/datasets/exploration_dataset.py

Exploration de l'arborescence des datasets sur le serveur, et droits d'accès
des utilisateurs.

list_folder_contents ne lit qu'UN SEUL niveau à la fois (jamais de
parcours récursif complet d'un dossier). C'est à l'interface d'appeler
cette fonction niveau par niveau, au fur et à mesure que l'admin
explore l'arborescence, pour rester rapide même sur de gros dossiers.

Ce module n'importe jamais Streamlit, pour rester cohérent avec
modules/users.py et pouvoir être testé indépendamment de l'affichage.
"""

import stat

import paramiko

from modules.datasets.sftp import obtenir_sftp


def list_folder_contents(chemin: str) -> list:
    """
    Liste le contenu d'UN SEUL niveau d'un dossier distant (sans entrer
    dans les sous-dossiers).

    Renvoie une liste de dictionnaires avec les clés "nom", "chemin" et
    "est_dossier", triée par ordre alphabétique (dossiers d'abord).

    Renvoie une liste vide si la connexion échoue ou si le dossier est
    inaccessible : c'est à l'interface d'afficher un message dans ce cas.
    """
    try:
        sftp = obtenir_sftp()
    except (paramiko.SSHException, OSError):
        return []

    elements = []
    try:
        for entree in sftp.listdir_attr(chemin):
            chemin_entree = f"{chemin.rstrip('/')}/{entree.filename}"
            elements.append(
                {
                    "nom": entree.filename,
                    "chemin": chemin_entree,
                    "est_dossier": stat.S_ISDIR(entree.st_mode),
                }
            )
    except IOError:
        elements = []

    # Tri alphabétique, dossiers d'abord, pour une lecture plus naturelle
    elements.sort(key=lambda e: (not e["est_dossier"], e["nom"]))
    return elements


def mettre_a_jour_selection(selection: set, chemin: str, coche: bool) -> set:
    """
    Renvoie une nouvelle sélection de chemins, avec `chemin` ajouté si
    `coche` vaut True, ou retiré sinon.

    La sélection d'origine n'est pas modifiée. Cette fonction ne dépend
    pas de Streamlit : c'est l'interface qui l'appelle à chaque clic.
    """
    nouvelle_selection = set(selection)
    if coche:
        nouvelle_selection.add(chemin)
    else:
        nouvelle_selection.discard(chemin)
    return nouvelle_selection


def chemin_relatif(racine: str, chemin: str) -> str:
    """
    Renvoie `chemin` sans le préfixe `racine`, pour un affichage plus court.

    Si `chemin` n'est pas situé sous la racine, il est renvoyé tel quel.
    """
    base = racine.rstrip("/") + "/"
    if chemin.startswith(base):
        return chemin[len(base):]
    return chemin


def get_datasets_autorises(users, username: str) -> list:
    """
    Renvoie la liste des chemins de datasets autorisés pour un utilisateur.

    La lecture se fait en base à chaque appel (et non depuis la session),
    pour que les changements faits par l'admin s'appliquent immédiatement.
    Renvoie une liste vide si l'utilisateur n'existe pas ou n'a aucun accès.
    """
    user = users.find_one({"username": username}, {"datasets_access": 1})
    if not user:
        return []
    return user.get("datasets_access") or []