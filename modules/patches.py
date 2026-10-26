"""
modules/patches.py

Lecture des versions préparées (patches) d'un dataset, et calculs liés au
patching des cubes HSI.

Les patches sont rangés dans le dataset lui-même, dans le dossier
hsi-data-patching (voir scripts_serveur/data_utils.py) :

    <dataset>/hsi-data-patching/HSI/csv_for_dataloader/{train,test,val}/{format}/

Une version est un format, par exemple w100_h100_sl50_sc80. Un split est
patché pour un format quand le CSV à 100 % existe, par exemple :

    .../csv_for_dataloader/train/w100_h100_sl50_sc80/100%_train_w100_h100_sl50_sc80.csv

C'est le dernier fichier écrit par le patching : 
s'il est là, le split est complet.

Comme le package modules/datasets, ce module n'importe jamais Streamlit et réutilise la
connexion SFTP partagée de modules/datasets/sftp.py.
"""

import re
from datetime import datetime

import paramiko

from modules.datasets.sftp import lister_noms, obtenir_sftp
from modules.datasets.stats import SPLITS

# Dossier des patches, à l'intérieur du dataset (même nom que dans data_utils.py)
NOM_DOSSIER_PATCHING = "hsi-data-patching"

# Forme d'un nom de format, par exemple w100_h100_sl50_sc80. Les autres
# dossiers sont ignorés. Cette règle existe aussi dans data_utils.py, qui
# tourne sur le serveur et ne peut pas être importé ici.
MOTIF_FORMAT = re.compile(r"^w\d+_h\d+_sl\d+_sc\d+$")


# ---------------------------------------------------------------------------
# Lecture des versions préparées (accès au serveur)
# ---------------------------------------------------------------------------


def chemin_patching(chemin_dataset: str) -> str:
    """Renvoie le dossier hsi-data-patching d'un dataset."""
    return f"{chemin_dataset.rstrip('/')}/{NOM_DOSSIER_PATCHING}"


def chemin_marqueur(chemin_dataset: str, split: str, nom_format: str) -> str:
    """
    Renvoie le chemin du CSV à 100 % de HSI, qui prouve qu'un split est
    patché pour un format.

    Sur le disque, les splits sont écrits en minuscules (train, test, val).
    """
    nom_split = split.lower()
    dossier = (
        f"{chemin_patching(chemin_dataset)}/HSI/csv_for_dataloader/"
        f"{nom_split}/{nom_format}"
    )
    return f"{dossier}/100%_{nom_split}_{nom_format}.csv"


def date_modification(sftp, chemin: str):
    """Renvoie la date de modification d'un fichier distant, ou None s'il n'existe pas."""
    try:
        return sftp.stat(chemin).st_mtime
    except IOError:
        return None


def lister_versions(chemin_dataset: str) -> list:
    """
    Liste les versions préparées d'un dataset.

    Renvoie une liste de dictionnaires triée par nom, avec les clés :
      - "nom" : le format, par exemple w100_h100_sl50_sc80
      - "splits_prets" : les splits patchés pour ce format (Train, Test, Val)
      - "date_creation" : date ISO du CSV à 100 % le plus récent

    Un format dont aucun split n'a son CSV à 100 % n'est pas listé (patching
    interrompu). La liste est vide si le dataset n'a pas encore de patches.

    Lève ConnectionError si le serveur est injoignable : c'est à
    l'interface d'afficher un message dans ce cas.
    """
    try:
        sftp = obtenir_sftp()
    except (paramiko.SSHException, OSError):
        raise ConnectionError("Serveur injoignable")

    racine = chemin_patching(chemin_dataset)

    # Pour chaque format trouvé : la date du CSV à 100 % de chaque split prêt
    formats = {}
    for split in SPLITS:
        dossier_split = f"{racine}/HSI/csv_for_dataloader/{split.lower()}"
        for nom_format in lister_noms(sftp, dossier_split) or []:
            if not MOTIF_FORMAT.match(nom_format):
                continue
            date = date_modification(sftp, chemin_marqueur(chemin_dataset, split, nom_format))
            if date is not None:
                formats.setdefault(nom_format, {})[split] = date

    versions = []
    for nom_format in sorted(formats):
        dates = formats[nom_format]
        plus_recente = max(dates.values())
        versions.append(
            {
                "nom": nom_format,
                "splits_prets": [s for s in SPLITS if s in dates],
                "date_creation": datetime.fromtimestamp(plus_recente).isoformat(timespec="seconds"),
            }
        )
    return versions


def splits_non_patches(versions: list, nom_format: str) -> list:
    """
    Renvoie les splits qui ne sont pas encore patchés pour un format.

    Si le format n'a aucune version, tous les splits sont à patcher. Si la
    liste renvoyée est vide, le format est entièrement patché : il ne doit
    plus être proposé à la création.
    """
    version = next((v for v in versions if v["nom"] == nom_format), None)
    if version is None:
        return list(SPLITS)
    return [s for s in SPLITS if s not in version["splits_prets"]]


# ---------------------------------------------------------------------------
# Calculs liés au patching (fonctions pures, sans accès au serveur)
# ---------------------------------------------------------------------------


def estimer_nb_patches(dimensions: dict, parametres: dict) -> int:
    """
    Estime le nombre de patches obtenus en découpant un cube.

    Le calcul suit celui de torch.nn.functional.unfold utilisé dans le
    script de patching : une fenêtre de n_lines lignes sur patch_size
    colonnes, déplacée par pas de stride_lines lignes et stride_cols colonnes.

    Paramètres :
      - dimensions : {"lignes": int, "colonnes": int, "bandes": int}, ou None
        si les dimensions du cube sont illisibles.
      - parametres : {"n_lines", "patch_size", "stride_lines", "stride_cols",
        "full_width"}. En largeur complète, patch_size et stride_cols sont
        ignorés (la fenêtre couvre toute la largeur du cube).

    Renvoie None si les dimensions sont inconnues, 0 si la fenêtre est plus
    grande que le cube (aucun patch possible), sinon le nombre de patches.
    """
    if dimensions is None:
        return None

    lignes = dimensions["lignes"]
    colonnes = dimensions["colonnes"]
    n_lines = parametres["n_lines"]
    stride_lines = parametres["stride_lines"]

    # En largeur complète, la fenêtre couvre toute la largeur du cube
    if parametres["full_width"]:
        patch_size = colonnes
        stride_cols = colonnes
    else:
        patch_size = parametres["patch_size"]
        stride_cols = parametres["stride_cols"]

    # La fenêtre ne tient pas dans le cube : aucun patch possible
    if lignes < n_lines or colonnes < patch_size:
        return 0

    # Nombre de positions de la fenêtre dans chaque direction
    nb_en_lignes = (lignes - n_lines) // stride_lines + 1
    nb_en_colonnes = (colonnes - patch_size) // stride_cols + 1

    return nb_en_lignes * nb_en_colonnes