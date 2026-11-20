"""
modules/apprentissage/etape_lancement_suivi.py

Étape 4 de la page Apprentissage : lancement et suivi de l'entraînement.
Ce fichier prépare ce que la page affiche : l'état et le choix des GPU, le
récapitulatif de la configuration validée à l'étape Paramétrage, et l'état
de l'entraînement en cours.

Ce module ne contient aucune interface Streamlit : l'affichage est dans
ui/apprentissage/etape4_lancement.py. Le lancement et l'arrêt de
l'entraînement sont dans gestion_entrainement.py.
"""

import subprocess

from modules.apprentissage.etape_parametrage import TITRES_BLOCS, TYPES_APPRENTISSAGE
from modules.apprentissage.gestion_entrainement import MLFLOW_URI

# Titre du bloc de choix du GPU
TITRE_BLOC_GPU = "Choix du GPU"

# États de l'entraînement pour lesquels le suivi se rafraîchit tout seul
ETATS_ACTIFS = ("demarrage", "en_cours")


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------

def lire_gpus() -> list:
    """
    Renvoie l'état des GPU de l'ordinateur, lu avec nvidia-smi.

    La mémoire est exprimée en Go. La liste est vide si aucun GPU n'est
    détecté (nvidia-smi absent ou en erreur).
    """
    try:
        sortie = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout

        gpus = []
        for ligne in sortie.strip().splitlines():
            index, utilisation, utilisee, totale = [v.strip() for v in ligne.split(",")]
            gpus.append({
                "index": int(index),
                "utilisation": int(utilisation),
                "memoire_utilisee": round(float(utilisee) / 1024, 1),  # Mo -> Go
                "memoire_totale": round(float(totale) / 1024, 1),
            })
        return gpus
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def lignes_gpus(gpus: list) -> list:
    """Prépare les lignes du tableau d'état des GPU."""
    return [
        {
            "GPU": f"GPU {g['index']}",
            "Utilisation (%)": g["utilisation"],
            "Mémoire utilisée (Go)": g["memoire_utilisee"],
            "Mémoire totale (Go)": g["memoire_totale"],
        }
        for g in gpus
    ]


def libelle_gpu(gpu: dict) -> str:
    """Renvoie le texte d'un choix de GPU, par exemple "GPU 1 (87 % utilisé)"."""
    return f"GPU {gpu['index']} ({gpu['utilisation']} % utilisé)"


# ---------------------------------------------------------------------------
# Récapitulatif de la configuration
# ---------------------------------------------------------------------------

def formater_valeur(valeur) -> str:
    """Met une valeur en forme pour l'affichage : Oui/Non pour un booléen."""
    if isinstance(valeur, bool):
        return "Oui" if valeur else "Non"
    return str(valeur)


def blocs_recapitulatif(config: dict) -> list:
    """
    Prépare le récapitulatif de la configuration, bloc par bloc.

    Renvoie une liste de (titre, teinte, lignes) dans l'ordre des expanders
    de l'étape Paramétrage, où lignes est une liste de (nom, valeur) déjà
    mises en forme. La teinte est celle du bloc dans la page (bleu, violet,
    turquoise, orange).
    """
    # Libellé lisible du type d'apprentissage (l'inverse de TYPES_APPRENTISSAGE)
    libelles_types = {valeur: nom for nom, valeur in TYPES_APPRENTISSAGE.items()}
    labels = "0 (normaux)" if config["labels_retenus"] == [0] else "Tous"

    return [
        (TITRES_BLOCS["modele"], "bleu", [
            ("Type d'apprentissage", libelles_types[config["type_apprentissage"]]),
            ("Modèle", config["modele"]),
        ]),
        (TITRES_BLOCS["hyperparametres"], "violet", [
            (nom, formater_valeur(valeur))
            for nom, valeur in config["hyperparametres"].items()
        ]),
        (TITRES_BLOCS["generaux"], "turquoise", [
            (nom, formater_valeur(valeur))
            for nom, valeur in config["parametres_generaux"].items()
        ]),
        (TITRES_BLOCS["donnees"], "orange", [
            ("Split", config["split"]),
            ("Format de patches", config["format_patches"]),
            ("Fraction du CSV", f"{config['fraction_csv']} %"),
            ("Labels retenus", labels),
        ]),
    ]


# ---------------------------------------------------------------------------
# Suivi de l'entraînement
# ---------------------------------------------------------------------------

def etat_du_run(run: dict) -> str:
    """
    Renvoie l'état d'un entraînement : demarrage, en_cours, termine, arrete ou erreur.

    Si le processus a disparu sans écrire d'état final (plantage, arrêt
    depuis le terminal), l'entraînement est considéré en erreur.
    """
    etat = run["statut"].get("state")
    if etat == "done":
        return "termine"
    if etat == "stopped":
        return "arrete"
    if etat == "error" or not run["vivant"]:
        return "erreur"
    return "en_cours" if etat == "running" else "demarrage"


def url_mlflow(statut: dict) -> str:
    """Renvoie le lien vers le run dans MLflow (ou vers l'accueil tant que le run n'existe pas)."""
    run_id = statut.get("run_id")
    experience = statut.get("experiment_id")
    if run_id and experience:
        return f"{MLFLOW_URI}/#/experiments/{experience}/runs/{run_id}"
    return MLFLOW_URI