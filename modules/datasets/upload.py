"""
modules/datasets/upload.py

Envoi d'un dataset (archive zip) sur le serveur, dans l'espace d'un
utilisateur, puis ajout de l'accès correspondant en base.

Le contrôle de l'archive se fait AVANT tout envoi, pour ne rien écrire sur
le serveur si l'archive est suspecte. Un dataset qui existe déjà n'est
jamais écrasé.

Ce module n'importe jamais Streamlit.
"""

import os
import re
import shutil
import zipfile

from modules.datasets.chemins import DATASETS_PATH
from modules.datasets.stats import SPLITS

# Un nom (de dataset ou d'utilisateur) ne contient que des lettres, des
# chiffres, des tirets et des underscores : pas de "/" ni de ".."
MOTIF_NOM = re.compile(r"^[A-Za-z0-9_-]+$")


def nom_valide(nom: str) -> bool:
    """Indique si un nom est utilisable comme nom de dossier sur le serveur."""
    return bool(MOTIF_NOM.fullmatch(nom or ""))


def dossier_utilisateur(username: str) -> str:
    """Renvoie le dossier personnel d'un utilisateur : <racine>/<username>."""
    return f"{DATASETS_PATH.rstrip('/')}/{username}"


def chemin_dataset_utilisateur(username: str, nom_dataset: str) -> str:
    """Renvoie le chemin d'un dataset : <racine>/<username>/<nom_dataset>."""
    return f"{dossier_utilisateur(username)}/{nom_dataset}"


def ajouter_dataset_acces(users, username: str, chemin: str) -> None:
    """
    Ajoute un chemin dans la liste datasets_access de l'utilisateur.

    $addToSet n'ajoute le chemin que s'il n'y est pas déjà (pas de doublon).
    """
    users.update_one(
        {"username": username},
        {"$addToSet": {"datasets_access": chemin}},
    )


def creer_dossier(chemin: str) -> None:
    """Crée un dossier, ainsi que ses parents s'ils manquent (rien si déjà là)."""
    os.makedirs(chemin, exist_ok=True)


def supprimer_dossier(chemin: str) -> None:
    """
    Supprime un dossier et tout son contenu.

    Sert uniquement à nettoyer un dataset à moitié envoyé après une erreur.
    """
    shutil.rmtree(chemin)


def _preparer_entrees(archive):
    """
    Prépare la liste des éléments d'une archive zip à envoyer.

    Renvoie (entrees, erreur) :
      - entrees : liste de (info_zip, chemin_relatif)
      - erreur : texte d'erreur, ou None si tout va bien

    Le contrôle se fait AVANT tout envoi, pour ne rien écrire sur le serveur
    si l'archive est suspecte.
    """
    # On écarte les fichiers parasites ajoutés par macOS
    infos = [
        i for i in archive.infolist()
        if "__MACOSX" not in i.filename.split("/")
        and not i.filename.endswith(".DS_Store")
    ]
    if not infos:
        return None, "L'archive est vide."

    # Si l'archive contient un seul dossier qui englobe tout (et que ce n'est
    # pas Train, Test ou Val), on l'enlève des chemins
    premiers = {i.filename.split("/")[0] for i in infos}
    prefixe = ""
    if len(premiers) == 1:
        seul = premiers.pop()
        if seul.lower() not in [s.lower() for s in SPLITS]:
            prefixe = seul + "/"

    entrees = []
    for info in infos:
        relatif = info.filename
        if prefixe and relatif.startswith(prefixe):
            relatif = relatif[len(prefixe):]
        relatif = relatif.rstrip("/")
        if not relatif:
            continue

        # Protection "zip slip" : aucun chemin absolu ni remontant (..)
        parties = relatif.split("/")
        if relatif.startswith("/") or "\\" in relatif or ".." in parties:
            return None, "L'archive contient un chemin non autorisé : " + info.filename
        entrees.append((info, relatif))

    if not entrees:
        return None, "L'archive est vide."
    return entrees, None


def envoyer_zip(fichier_zip, username: str, nom_dataset: str):
    """
    Envoie le contenu d'une archive zip sur le serveur, dans l'espace de
    l'utilisateur : <racine>/<username>/<nom_dataset>/.

    `fichier_zip` est l'objet renvoyé par st.file_uploader. Les fichiers de
    l'archive sont extraits directement vers le dossier du dataset.

    Renvoie (succes, message, chemin) : `chemin` vaut None en cas d'échec.
    Un dataset qui existe déjà n'est jamais écrasé.
    """
    # Vérification des noms (ils servent à construire un chemin)
    if not nom_valide(nom_dataset):
        return False, (
            "Nom invalide : utilisez uniquement des lettres, des chiffres, "
            "des tirets et des underscores."
        ), None
    if not nom_valide(username):
        return False, "Le nom d'utilisateur ne peut pas servir de nom de dossier.", None

    chemin = chemin_dataset_utilisateur(username, nom_dataset)

    # Ouverture et contrôle de l'archive
    try:
        archive = zipfile.ZipFile(fichier_zip)
    except zipfile.BadZipFile:
        return False, "Le fichier n'est pas une archive zip valide.", None

    entrees, erreur = _preparer_entrees(archive)
    if erreur:
        return False, erreur, None

    # Refus si le dataset existe déjà
    if os.path.exists(chemin):
        return False, "Un dataset portant ce nom existe déjà.", None

    # Envoi : on recrée l'arborescence puis on copie chaque fichier
    try:
        creer_dossier(chemin)
        dossiers_crees = set()
        for info, relatif in entrees:
            cible = f"{chemin}/{relatif}"
            if info.is_dir():
                creer_dossier(cible)
                continue
            # Le dossier parent du fichier est créé une seule fois
            dossier = os.path.dirname(cible)
            if dossier not in dossiers_crees:
                creer_dossier(dossier)
                dossiers_crees.add(dossier)
            with archive.open(info) as source, open(cible, "wb") as destination:
                shutil.copyfileobj(source, destination)
    except OSError as erreur_envoi:
        # On nettoie le dataset à moitié envoyé, pour pouvoir réessayer
        try:
            supprimer_dossier(chemin)
        except OSError:
            pass
        return False, f"L'envoi a échoué : {erreur_envoi}", None

    return True, f"Le dataset « {nom_dataset} » a été envoyé ({len(entrees)} éléments).", chemin


def ajouter_dataset(users, fichier_zip, username: str, nom_dataset: str):
    """
    Ajoute un dataset pour un utilisateur : envoie l'archive zip sur le
    serveur, puis donne l'accès à l'utilisateur en base si l'envoi a réussi.

    Renvoie (succes, message), le message étant destiné à l'affichage.
    """
    succes, message, chemin = envoyer_zip(fichier_zip, username, nom_dataset)
    if succes:
        ajouter_dataset_acces(users, username, chemin)
    return succes, message