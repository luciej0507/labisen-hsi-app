"""
modules/serveur.py

Lancement et suivi des traitements lourds sur le serveur : patching des
cubes (scripts_serveur/data_utils.py) et, plus tard, entraînement.

L'application tourne sur le même serveur que les GPU et les datasets : un
traitement est donc un simple sous-processus, sans SSH. Il est détaché de
l'application (nouvelle session) : il continue si la page est rechargée ou
si Streamlit redémarre.

L'avancement est lu dans un fichier JSON que le script écrit dans
<dataset>/hsi-data-patching/. Ce fichier ne sert qu'à l'affichage : ce sont
les CSV à 100 % qui prouvent qu'un split est patché.

Ce module n'importe jamais Streamlit. Il suppose un système Linux (/proc).
"""

import json
import os
import signal
import subprocess
import sys
from collections import deque
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from modules.patches import chemin_patching

load_dotenv()

# Racine du projet (le dossier qui contient modules/ et scripts_serveur/)
RACINE_PROJET = Path(__file__).resolve().parent.parent

# Script de patching, qui s'exécute avec les bibliothèques d'apprentissage
SCRIPT_PATCHING = RACINE_PROJET / "scripts_serveur" / "data_utils.py"

# Python utilisé pour lancer les scripts. Par défaut, celui de l'application
# (un seul environnement, avec torch). La variable PYTHON_JOBS du .env
# permet d'utiliser un autre environnement, par exemple shared-env.
PYTHON_JOBS = os.getenv("PYTHON_JOBS") or sys.executable

# Fichiers écrits dans <dataset>/hsi-data-patching/
NOM_SUIVI = "suivi_patching.json"
NOM_LOG = "patching.log"

# Sans numéro de processus connu, un job qui n'a rien écrit depuis ce délai
# (en secondes) est considéré comme interrompu
DELAI_INTERRUPTION = 300

# Une GPU est libre sous ces deux seuils
SEUIL_MEMOIRE_LIBRE_MO = 1024
SEUIL_UTILISATION_LIBRE = 5


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------


def lister_gpus() -> list:
    """
    Liste les GPU du serveur avec leur occupation.

    Renvoie une liste de dictionnaires (index, nom, memoire_utilisee_mo,
    memoire_totale_mo, utilisation, libre). La liste est vide si nvidia-smi
    est absent ou ne répond pas : c'est à l'interface d'afficher un message.
    """
    commande = [
        "nvidia-smi",
        "--query-gpu=index,name,memory.used,memory.total,utilization.gpu",
        "--format=csv,noheader,nounits",
    ]
    try:
        sortie = subprocess.run(
            commande, capture_output=True, text=True, timeout=10, check=True
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []

    gpus = []
    for ligne in sortie.strip().splitlines():
        # Le nom d'une GPU peut contenir une virgule : on lit les valeurs par la droite
        morceaux = [m.strip() for m in ligne.split(",")]
        try:
            index = int(morceaux[0])
            utilisee = int(morceaux[-3])
            totale = int(morceaux[-2])
            utilisation = int(morceaux[-1])
        except (ValueError, IndexError):
            continue  # ligne illisible (valeur [N/A] par exemple)
        gpus.append(
            {
                "index": index,
                "nom": ", ".join(morceaux[1:-3]),
                "memoire_utilisee_mo": utilisee,
                "memoire_totale_mo": totale,
                "utilisation": utilisation,
                "libre": utilisee < SEUIL_MEMOIRE_LIBRE_MO
                and utilisation < SEUIL_UTILISATION_LIBRE,
            }
        )
    return gpus


# ---------------------------------------------------------------------------
# Lancement d'un job
# ---------------------------------------------------------------------------


def lancer_job(commande: list, fichier_log: str, gpu=None) -> int:
    """
    Lance une commande en arrière-plan, détachée de l'application, et
    renvoie le numéro de son processus.

    La commande est une liste (pas de shell, donc rien à échapper). Sa sortie
    est écrite dans `fichier_log`, qui est recréé à chaque lancement. Si `gpu`
    est donné, le job ne voit que cette GPU (numérotée comme dans nvidia-smi).
    """
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"  # le journal se remplit au fil de l'eau
    if gpu is not None:
        env["CUDA_DEVICE_ORDER"] = "PCI_BUS_ID"  # même numérotation que nvidia-smi
        env["CUDA_VISIBLE_DEVICES"] = str(int(gpu))

    os.makedirs(os.path.dirname(fichier_log), exist_ok=True)
    with open(fichier_log, "wb") as journal:
        processus = subprocess.Popen(
            commande,
            stdin=subprocess.DEVNULL,
            stdout=journal,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,  # survit à l'application et permet de l'arrêter en bloc
        )
    return processus.pid


def processus_actif(pid) -> bool:
    """
    Indique si le processus `pid` est un job de patching encore vivant.

    On lit /proc pour vérifier que le numéro correspond bien à notre script :
    cela évite de confondre avec un autre processus qui aurait réutilisé le
    numéro, et un processus terminé mais pas encore récupéré (zombie) a une
    ligne de commande vide, donc il compte comme arrêté.
    """
    if pid is None:
        return False
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as fichier:
            ligne_de_commande = fichier.read()
    except (OSError, ValueError):
        return False
    return SCRIPT_PATCHING.name.encode() in ligne_de_commande


# ---------------------------------------------------------------------------
# Suivi du patching
# ---------------------------------------------------------------------------


def chemin_suivi(chemin_dataset: str) -> str:
    """Renvoie le fichier JSON d'avancement du patching d'un dataset."""
    return os.path.join(chemin_patching(chemin_dataset), NOM_SUIVI)


def chemin_log(chemin_dataset: str) -> str:
    """Renvoie le journal du dernier patching d'un dataset."""
    return os.path.join(chemin_patching(chemin_dataset), NOM_LOG)


def maintenant() -> str:
    """Renvoie l'heure actuelle au format ISO, sans les fractions de seconde."""
    return datetime.now().isoformat(timespec="seconds")


def ecrire_suivi(fichier: str, suivi: dict):
    """
    Écrit le fichier de suivi. Il est écrit dans un fichier temporaire puis
    renommé, pour ne jamais être lu à moitié.
    """
    suivi["maj"] = maintenant()
    temporaire = fichier + ".tmp"
    with open(temporaire, "w", encoding="utf-8") as sortie:
        json.dump(suivi, sortie, ensure_ascii=False)
    os.replace(temporaire, fichier)


def job_interrompu(suivi: dict) -> bool:
    """
    Indique si un job noté "en cours" s'est en réalité arrêté.

    Avec un numéro de processus, on regarde s'il tourne encore (un cube très
    long ne fait donc pas croire à une panne). Sans numéro, on se base sur la
    date de dernière mise à jour.
    """
    pid = suivi.get("pid")
    if pid is not None:
        return not processus_actif(pid)
    try:
        derniere_maj = datetime.fromisoformat(suivi["maj"])
    except (KeyError, TypeError, ValueError):
        return False
    return (datetime.now() - derniere_maj).total_seconds() > DELAI_INTERRUPTION


def lire_suivi(chemin_dataset: str):
    """
    Lit l'avancement du dernier patching d'un dataset.

    Renvoie un dictionnaire (etat, format, splits, cubes_total, cubes_faits,
    cube_courant, message, ...) ou None s'il n'y a jamais eu de patching.
    L'état vaut "en cours", "termine", "erreur", "annule" ou "interrompu"
    (job disparu sans avoir terminé).
    """
    try:
        with open(chemin_suivi(chemin_dataset), encoding="utf-8") as fichier:
            suivi = json.load(fichier)
    except (OSError, ValueError):
        return None

    if suivi.get("etat") == "en cours" and job_interrompu(suivi):
        suivi["etat"] = "interrompu"
        suivi["message"] = "Le traitement s'est arrêté sans terminer (voir le journal)."
    return suivi


def job_en_cours(chemin_dataset: str) -> bool:
    """Indique si un patching tourne actuellement sur ce dataset."""
    suivi = lire_suivi(chemin_dataset)
    return suivi is not None and suivi["etat"] == "en cours"


def lire_log(chemin_dataset: str, nb_lignes: int = 15) -> str:
    """
    Renvoie les dernières lignes du journal du patching, ou un texte vide
    s'il n'y a pas de journal. Utile pour afficher la cause d'une erreur.
    """
    try:
        with open(chemin_log(chemin_dataset), encoding="utf-8", errors="replace") as fichier:
            return "".join(deque(fichier, maxlen=nb_lignes))
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Patching
# ---------------------------------------------------------------------------


def construire_commande_patching(chemin_dataset, splits, parametres, fichier_suivi) -> list:
    """
    Construit la commande qui lance data_utils.py.

    `parametres` : n_lines, patch_size, stride_lines, stride_cols, full_width
    (patch_size et stride_cols valent None en largeur complète).
    """
    commande = [
        PYTHON_JOBS,
        str(SCRIPT_PATCHING),
        "--dataset", chemin_dataset,
        "--splits", *splits,
        "--n-lines", str(int(parametres["n_lines"])),
        "--stride-lines", str(int(parametres["stride_lines"])),
        "--suivi", fichier_suivi,
    ]
    if parametres["full_width"]:
        commande.append("--full-width")
    else:
        commande += [
            "--patch-size", str(int(parametres["patch_size"])),
            "--stride-cols", str(int(parametres["stride_cols"])),
        ]
    return commande


def lancer_patching(chemin_dataset: str, splits: list, parametres: dict) -> int:
    """
    Lance le patching d'un dataset en arrière-plan et renvoie le numéro du
    processus.

    Lève FileNotFoundError si le dataset est introuvable sur ce serveur,
    et RuntimeError si un patching tourne déjà sur ce dataset.
    """
    if not os.path.isdir(chemin_dataset):
        raise FileNotFoundError(f"Dataset introuvable sur ce serveur : {chemin_dataset}")
    if job_en_cours(chemin_dataset):
        raise RuntimeError("Un patching est déjà en cours pour ce dataset.")

    fichier_suivi = chemin_suivi(chemin_dataset)
    commande = construire_commande_patching(chemin_dataset, splits, parametres, fichier_suivi)
    pid = lancer_job(commande, chemin_log(chemin_dataset))

    # Le script met plusieurs secondes à démarrer (chargement de torch) : on
    # écrit tout de suite un premier suivi, pour que la page voie le job et
    # qu'un second lancement soit refusé. Le script le remplace ensuite.
    ecrire_suivi(
        fichier_suivi,
        {
            "etat": "en cours",
            "format": "",
            "splits": list(splits),
            "cubes_total": 0,
            "cubes_faits": 0,
            "cube_courant": "",
            "message": "Démarrage...",
            "pid": pid,
            "debut": maintenant(),
        },
    )
    return pid


def annuler_patching(chemin_dataset: str) -> bool:
    """
    Arrête le patching en cours d'un dataset.

    Renvoie False s'il n'y avait rien à arrêter. Les fichiers déjà écrits
    restent sur le disque : le split interrompu n'a pas de CSV à 100 %, donc
    il n'est pas considéré comme patché, et il sera nettoyé au prochain lancement.
    """
    suivi = lire_suivi(chemin_dataset)
    if suivi is None or suivi["etat"] != "en cours":
        return False

    # On n'arrête que si le numéro correspond bien à notre script
    pid = suivi.get("pid")
    if processus_actif(pid):
        try:
            os.killpg(int(pid), signal.SIGTERM)  # le job a sa propre session : on l'arrête en bloc
        except ProcessLookupError:
            pass

    suivi["etat"] = "annule"
    suivi["message"] = "Patching annulé."
    suivi["fin"] = maintenant()
    ecrire_suivi(chemin_suivi(chemin_dataset), suivi)
    return True