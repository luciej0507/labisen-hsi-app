"""
modules/apprentissage/etape_dataset.py

Étape 1 de la page Apprentissage : choix du dataset.
"""

from modules.datasets.exploration_dataset import get_datasets_autorises
from modules.datasets.stats import calculer_stats


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