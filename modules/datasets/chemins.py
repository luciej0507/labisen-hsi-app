"""
modules/datasets/chemins.py

Racine des datasets et petits utilitaires pour parcourir les dossiers.

L'application tourne sur le même serveur que les datasets : on lit donc
directement le disque (os, shutil), sans aucune connexion réseau.

La racine des datasets est lue dans le fichier .env (variable DATASETS_PATH),
comme MONGO_URI dans db_mongo.py.

Ce module n'importe jamais Streamlit.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# Dossier qui contient les datasets (chemin absolu sur le serveur)
DATASETS_PATH = os.getenv(
    "DATASETS_PATH", "/mnt/lslteam/SIIRI/CodePythonSIIRI/"
)

# Dossiers dont le nom peut être suivi d'un suffixe (en minuscules).
# Exemple : "HSI-Hybercube" est reconnu comme le dossier "HSI".
DOSSIERS_A_PREFIXE = ("hsi",)


def lister_noms(chemin):
    """Renvoie les noms contenus dans un dossier, ou None s'il est inaccessible."""
    try:
        return os.listdir(chemin)
    except OSError:
        return None


def trouver(noms, voulu):
    """
    Cherche un dossier par son nom, sans tenir compte de la casse
    (train = Train).

    Pour les dossiers de DOSSIERS_A_PREFIXE (HSI), on accepte aussi un nom
    qui commence par ce préfixe (HSI-Hybercube), mais seulement si aucun
    nom exact n'existe : le nom exact reste toujours prioritaire.
    """
    # 1) Nom exact, à la casse près
    for nom in noms:
        if nom.lower() == voulu.lower():
            return nom

    # 2) Nom qui commence par le préfixe (tri pour un résultat stable)
    if voulu.lower() in DOSSIERS_A_PREFIXE:
        for nom in sorted(noms):
            if nom.lower().startswith(voulu.lower()):
                return nom

    return None


def resoudre(base, sous_chemin):
    """
    Descend dans `sous_chemin` (ex : "Annotation/JSON") à partir de `base`,
    en tolérant les différences de casse. Renvoie le vrai chemin, ou None
    si un des dossiers n'existe pas.
    """
    chemin = base
    for partie in sous_chemin.split("/"):
        noms = lister_noms(chemin)
        if noms is None:
            return None
        reel = trouver(noms, partie)
        if reel is None:
            return None
        chemin = f"{chemin.rstrip('/')}/{reel}"
    return chemin
