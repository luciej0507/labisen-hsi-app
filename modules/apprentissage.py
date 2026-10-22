"""
modules/apprentissage.py

Logique de la page Apprentissage : étapes du parcours, règles de
verrouillage de la frise, lecture des datasets utilisables et préparation
des patches.

Le parcours est obligatoire : un dataset à l'état Complet, puis le
patching, puis le choix de l'entraînement, puis le récapitulatif.

Ce module n'importe jamais Streamlit, comme datasets.py et patches.py :
la page ne fait que l'affichage et appelle ces fonctions.
"""

import time
from datetime import datetime

from modules.datasets import (
    SPLITS,
    calculer_stats,
    get_datasets_autorises,
    lire_dimensions,
    lister_cubes,
)
from modules.patches import estimer_nb_patches, lister_versions, splits_non_patches

# Étapes du parcours, dans l'ordre d'affichage de la frise
ETAPES = [
    {"cle": "dataset", "titre": "Dataset"},
    {"cle": "patching", "titre": "Patching"},
    {"cle": "entrainement", "titre": "Entraînement"},
    {"cle": "recapitulatif", "titre": "Récapitulatif"},
]

# Choix de split source pour le patching : un split, ou tous ceux à patcher
TOUS_LES_SPLITS = "Tous les splits"
TOUS_LES_SPLITS_RESTANTS = "Tous les splits restants"

# Split indispensable pour utiliser une version à l'entraînement
SPLIT_ENTRAINEMENT = "Train"

# Valeurs proposées pour chaque paramètre du format des patches
CHOIX_N_LINES = [1, 100, 200, 300]
CHOIX_PATCH_SIZE = [100, 200, 300]
CHOIX_STRIDE_LINES = [1, 50, 100, 200]
CHOIX_STRIDE_COLS = [50, 80, 100, 200]


# ---------------------------------------------------------------------------
# Règles de la frise
# ---------------------------------------------------------------------------


def etapes_validees(dataset, version) -> list:
    """
    Renvoie une liste de booléens (un par étape) indiquant celles qui
    sont validées.

    - Dataset : validée dès qu'un dataset a été choisi.
    - Patching : validée dès qu'une version de patches a été choisie.
    - Les deux dernières étapes suivront avec leur contenu.
    """
    return [dataset is not None, version is not None, False, False]


def etape_accessible(index: int, validees: list) -> bool:
    """
    Indique si l'étape `index` est accessible.

    La première étape l'est toujours. Les suivantes ne le sont que si
    toutes les étapes précédentes sont validées.
    """
    return all(validees[:index])


def libelle_etape(index: int, validee: bool) -> str:
    """Renvoie le texte du bouton d'une étape, par exemple "1. Dataset"."""
    texte = f"{index + 1}. {ETAPES[index]['titre']}"
    if validee:
        texte += " (validé)"
    return texte


# ---------------------------------------------------------------------------
# Mises en forme
# ---------------------------------------------------------------------------


def formater_nombre(nombre: int) -> str:
    """Affiche un entier avec un espace comme séparateur de milliers."""
    return f"{nombre:,}".replace(",", " ")


def formater_splits(nombres_par_split: dict) -> str:
    """
    Met en forme un nombre par split.

    Exemple : {"Train": 1200, "Test": 300} devient "Train 1 200, Test 300".
    """
    return ", ".join(
        f"{nom} {formater_nombre(nombre)}" for nom, nombre in nombres_par_split.items()
    )


def formater_date(date_iso) -> str:
    """Transforme une date ISO (2026-10-16T11:30:00) en 16/10/2026 11:30."""
    try:
        return datetime.fromisoformat(date_iso).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return "inconnue"


# ---------------------------------------------------------------------------
# Étape 1 : choix du dataset
# ---------------------------------------------------------------------------


def lister_datasets_complets(users, username: str) -> list:
    """
    Renvoie les chemins des datasets autorisés pour l'utilisateur dont
    l'état est Complet (voir la page Gestion des BDD).

    Renvoie une liste vide si l'utilisateur n'a aucun accès ou si aucun
    dataset n'est complet.
    """
    chemins = get_datasets_autorises(users, username)
    return [c for c in chemins if calculer_stats(c)["etat"] == "Complet"]


def resume_dataset(chemin_dataset: str) -> dict:
    """
    Renvoie un petit résumé d'un dataset : nombre total de cubes, nombre
    de cubes annotés et nombre de cubes par split.
    """
    stats = calculer_stats(chemin_dataset)
    return {
        "total_cubes": stats["total_cubes"],
        "annotes": stats["annotes"],
        "cubes_par_split": stats["cubes_par_split"],
    }


# ---------------------------------------------------------------------------
# Étape 2 : versions déjà préparées
# ---------------------------------------------------------------------------


def lire_versions(chemin_dataset: str):
    """
    Renvoie les versions déjà préparées d'un dataset (liste vide s'il n'y
    en a aucune), ou None si le serveur est injoignable.
    """
    try:
        return lister_versions(chemin_dataset)
    except ConnectionError:
        return None


def lignes_versions(versions: list) -> list:
    """
    Prépare les lignes du tableau des versions déjà préparées : une ligne
    par version, avec les splits patchés et la date de création.
    """
    lignes = []
    for version in versions:
        lignes.append(
            {
                "Version": version["nom"],
                "Splits patchés": ", ".join(version["splits_prets"]),
                "Date de création": formater_date(version["date_creation"]),
            }
        )
    return lignes


def libelles_versions(versions: list) -> dict:
    """
    Renvoie le texte affiché dans la liste de choix pour chaque version,
    sous la forme {nom: "nom (Train, Test)"}.
    """
    return {
        v["nom"]: f"{v['nom']} ({', '.join(v['splits_prets'])})" for v in versions
    }


def trouver_version(versions: list, nom: str):
    """Renvoie la version qui porte ce nom, ou None."""
    return next((v for v in versions if v["nom"] == nom), None)


def version_utilisable(version: dict) -> bool:
    """
    Indique si une version peut servir à l'entraînement : le split Train
    doit être patché.
    """
    return SPLIT_ENTRAINEMENT in version["splits_prets"]


# ---------------------------------------------------------------------------
# Étape 2 : nouvelle version
# ---------------------------------------------------------------------------


def nom_dossier_format(
    n_lines, patch_size, stride_lines, stride_cols, full_width, largeur=None
) -> str:
    """
    Construit le nom du dossier d'une version à partir du format choisi.

    En largeur complète, le nom contient la largeur des cubes (voir
    largeur_commune) à la place de patch_size et de stride_cols.
    """
    if full_width:
        return f"w{n_lines}_h{largeur}_sl{stride_lines}_sc{largeur}"
    return f"w{n_lines}_h{patch_size}_sl{stride_lines}_sc{stride_cols}"


def construire_parametres(n_lines, patch_size, stride_lines, stride_cols, full_width) -> dict:
    """
    Regroupe les paramètres du format dans un dictionnaire.

    En largeur complète, patch_size et stride_cols ne s'appliquent pas :
    ils valent None.
    """
    return {
        "n_lines": n_lines,
        "patch_size": None if full_width else patch_size,
        "stride_lines": stride_lines,
        "stride_cols": None if full_width else stride_cols,
        "full_width": full_width,
    }


def splits_restants(versions: list, nom_dossier: str) -> list:
    """
    Renvoie les splits qui ne sont pas encore patchés pour ce format.

    Une liste vide signifie que le format est entièrement patché : on ne
    propose pas de le refaire.
    """
    return splits_non_patches(versions, nom_dossier)


def splits_deja_patches(restants: list) -> list:
    """Renvoie les splits déjà patchés, c'est-à-dire ceux qui ne sont pas dans `restants`."""
    return [s for s in SPLITS if s not in restants]


def options_split_source(restants: list) -> list:
    """
    Renvoie les choix du split source : un choix par split restant, précédé
    de "Tous les splits" (ou "Tous les splits restants" si certains sont
    déjà patchés) quand il y en a plusieurs.
    """
    if len(restants) <= 1:
        return list(restants)
    tous = TOUS_LES_SPLITS if len(restants) == len(SPLITS) else TOUS_LES_SPLITS_RESTANTS
    return [tous] + list(restants)


def splits_a_patcher(choix: str, restants: list) -> list:
    """Renvoie la liste des splits à patcher selon le choix de l'utilisateur."""
    if choix in (TOUS_LES_SPLITS, TOUS_LES_SPLITS_RESTANTS):
        return list(restants)
    return [choix]


# ---------------------------------------------------------------------------
# Étape 2 : dimensions des cubes, aperçu et lancement
# ---------------------------------------------------------------------------


def lire_dimensions_dataset(chemin_dataset: str) -> dict:
    """
    Lit les dimensions de tous les cubes du dataset, une seule fois.

    Renvoie {split: {nom du cube: dimensions}}, où les dimensions valent
    None si elles sont illisibles. Un split introuvable (ou un serveur
    injoignable) donne un dictionnaire vide.
    """
    dimensions = {}
    for split in SPLITS:
        dimensions[split] = {
            cube: lire_dimensions(chemin_dataset, split, cube)
            for cube in lister_cubes(chemin_dataset, split)
        }
    return dimensions


def largeur_commune(dimensions_dataset: dict):
    """
    Cherche la largeur (nombre de colonnes) commune à tous les cubes.

    Renvoie un couple (largeur, problème). Le problème est un texte à
    afficher quand la largeur ne peut pas être déterminée (dimensions
    illisibles ou cubes de largeurs différentes), sinon None.
    """
    largeurs = {
        dims["colonnes"]
        for cubes in dimensions_dataset.values()
        for dims in cubes.values()
        if dims is not None
    }
    if not largeurs:
        return None, "Dimensions des cubes illisibles : la largeur complète est indisponible."
    if len(largeurs) > 1:
        liste = ", ".join(str(largeur) for largeur in sorted(largeurs))
        return None, (
            f"Les cubes n'ont pas tous la même largeur ({liste}) : "
            "la largeur complète est impossible pour ce dataset."
        )
    return largeurs.pop(), None


def cubes_a_patcher(dimensions_dataset: dict, splits: list) -> list:
    """
    Renvoie la liste des cubes à patcher, sous la forme de couples
    (split, nom du cube), dans l'ordre des splits.
    """
    couples = []
    for split in splits:
        for cube in dimensions_dataset.get(split, {}):
            couples.append((split, cube))
    return couples


def apercu_patching(dimensions_dataset: dict, splits: list, parametres: dict) -> dict:
    """
    Estime le résultat du patching avant de le lancer.

    Renvoie un dictionnaire avec :
      - "nb_cubes" : nombre de cubes à patcher
      - "total_patches" : nombre total de patches estimés
      - "patches_par_split" : nombre de patches estimés par split
      - "illisibles" : nombre de cubes dont les dimensions sont illisibles
        (ils ne sont pas comptés dans l'estimation)
    """
    nb_cubes = 0
    illisibles = 0
    patches_par_split = {}

    for split in splits:
        cubes = dimensions_dataset.get(split, {})
        total_split = 0
        for dimensions in cubes.values():
            estimation = estimer_nb_patches(dimensions, parametres)
            if estimation is None:
                illisibles += 1
            else:
                total_split += estimation
        nb_cubes += len(cubes)
        patches_par_split[split] = total_split

    return {
        "nb_cubes": nb_cubes,
        "total_patches": sum(patches_par_split.values()),
        "patches_par_split": patches_par_split,
        "illisibles": illisibles,
    }


def lancer_patching_cube(chemin_dataset, split, nom_cube, parametres):
    """
    Lance le patching d'un cube.

    Fonction factice : à remplacer par le lancement du script
    data_utils.py sur le serveur (voir modules/serveur.py).
    """
    time.sleep(0.3)  # simulation d'un traitement, à supprimer