"""
modules/apprentissage/gestion_entrainement.py

Lancement, suivi et arrêt de l'entraînement, sans interface Streamlit.

L'entraînement est un processus Python indépendant (entrainement/fastflow_mlflow.py)
lancé dans sa propre session : il continue de tourner même si l'application
Streamlit est fermée. Tout passe par des fichiers :

    entrainements/run_en_cours.json         : PID et dossier du dernier entraînement lancé
    entrainements/runs/<date>/config.json   : configuration envoyée au script
    entrainements/runs/<date>/status.json   : état écrit par le script à chaque époque
    entrainements/runs/<date>/train.log     : sortie du script
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Racine du projet (ce fichier est dans modules/apprentissage/)
RACINE_PROJET = Path(__file__).resolve().parents[2]

# Script d'entraînement (avec hsi_datamodule.py et dataloader_patches.py à côté)
SCRIPT_ENTRAINEMENT = (
    RACINE_PROJET / "modules" / "apprentissage" / "entrainement" / "fastflow_mlflow.py"
)

# Dossier où sont rangés les runs, la base MLflow et ses artefacts
DOSSIER_ENTRAINEMENTS = RACINE_PROJET / "entrainements"
DOSSIER_RUNS = DOSSIER_ENTRAINEMENTS / "runs"
FICHIER_RUN_EN_COURS = DOSSIER_ENTRAINEMENTS / "run_en_cours.json"

# Serveur MLflow local
MLFLOW_HOTE = "127.0.0.1"
MLFLOW_PORT = 5000
MLFLOW_URI = f"http://{MLFLOW_HOTE}:{MLFLOW_PORT}"

# Arborescence des CSV dans un dataset :
# <dataset>/hsi_data_patching/HSI/csv_for_dataloader/<split>/<format>/<fraction>%_<split>_<format>.csv
DOSSIER_PATCHING = "hsi_data_patching"
DOSSIER_DONNEES = "HSI"
DOSSIER_CSV = "csv_for_dataloader"


# ---------------------------------------------------------------------------
# Petits utilitaires sur les fichiers JSON
# ---------------------------------------------------------------------------

def lire_json(chemin: Path):
    """Lit un fichier JSON. Renvoie None s'il n'existe pas ou n'est pas lisible."""
    try:
        return json.loads(Path(chemin).read_text())
    except (OSError, ValueError):
        return None


def ecrire_json(chemin: Path, contenu: dict):
    """Écrit un fichier JSON d'un seul coup, pour qu'il ne soit jamais lu à moitié."""
    chemin = Path(chemin)
    temporaire = chemin.with_suffix(".tmp")
    temporaire.write_text(json.dumps(contenu, indent=2, ensure_ascii=False))
    os.replace(temporaire, chemin)


# ---------------------------------------------------------------------------
# Serveur MLflow
# ---------------------------------------------------------------------------

def mlflow_actif() -> bool:
    """Indique si un serveur MLflow répond sur le port prévu."""
    with socket.socket() as connexion:
        connexion.settimeout(0.5)
        return connexion.connect_ex((MLFLOW_HOTE, MLFLOW_PORT)) == 0


def demarrer_mlflow():
    """Démarre le serveur MLflow s'il n'est pas déjà lancé (il survit à l'application)."""
    if mlflow_actif():
        return

    DOSSIER_ENTRAINEMENTS.mkdir(parents=True, exist_ok=True)
    commande = [
        sys.executable, "-m", "mlflow", "server",
        "--host", MLFLOW_HOTE,
        "--port", str(MLFLOW_PORT),
        "--backend-store-uri", f"sqlite:///{DOSSIER_ENTRAINEMENTS / 'mlflow.db'}",
        "--artifacts-destination", str(DOSSIER_ENTRAINEMENTS / "mlartifacts"),
    ]
    with open(DOSSIER_ENTRAINEMENTS / "mlflow_server.log", "ab") as journal:
        subprocess.Popen(
            commande,
            stdout=journal,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )

    # On attend (20 s au maximum) que le serveur réponde
    for _ in range(40):
        time.sleep(0.5)
        if mlflow_actif():
            return
    raise RuntimeError(
        "Le serveur MLflow n'a pas démarré (voir entrainements/mlflow_server.log)."
    )


# ---------------------------------------------------------------------------
# Lancement
# ---------------------------------------------------------------------------

def chemin_csv(dataset, split: str, format_patches: str, fraction: int) -> Path:
    """Construit le chemin du CSV d'un split, et vérifie qu'il existe."""
    dossier = (
        Path(dataset) / DOSSIER_PATCHING / DOSSIER_DONNEES / DOSSIER_CSV
        / split / format_patches
    )
    csv = dossier / f"{fraction}%_{split}_{format_patches}.csv"
    if not csv.exists():
        raise FileNotFoundError(f"CSV introuvable : {csv}")
    return csv


def lancer_entrainement(dataset, config: dict, gpu: int) -> Path:
    """
    Lance l'entraînement dans un processus détaché et renvoie son dossier de run.

    dataset : chemin du dataset choisi à l'étape 1
    config  : configuration validée à l'étape Paramétrage
    gpu     : indice du GPU choisi
    """
    run = lire_run_en_cours()
    if run is not None and run["vivant"]:
        raise RuntimeError("Un entraînement est déjà en cours.")

    # CSV d'entraînement, et de validation seulement si elle est activée
    format_patches = config["format_patches"]
    fraction = config["fraction_csv"]
    csv = {"train": str(chemin_csv(dataset, config["split"], format_patches, fraction))}
    if config["parametres_generaux"]["validation"]:
        csv["val"] = str(chemin_csv(dataset, "val", format_patches, fraction))

    demarrer_mlflow()

    # Un dossier par entraînement
    dossier = DOSSIER_RUNS / datetime.now().strftime("%Y%m%d_%H%M%S")
    dossier.mkdir(parents=True)

    # Ce fichier est lu par le script : configuration + chemins + GPU
    contenu = {
        **config,
        "dataset": str(dataset),
        # Les chemins des patches dans les CSV sont relatifs à ce dossier
        "racine_patches": str(Path(dataset) / DOSSIER_PATCHING),
        "csv": csv,
        "gpu": gpu,
        "mlflow_uri": MLFLOW_URI,
    }
    ecrire_json(dossier / "config.json", contenu)
    ecrire_json(dossier / "status.json", {"state": "starting"})

    # Le GPU est choisi avec CUDA_VISIBLE_DEVICES : le script ne voit que celui-là.
    # PYTHONPATH contient la racine du projet : le script peut ainsi importer
    # "modules.apprentissage..." comme le fait l'application.
    environnement = {
        **os.environ,
        "CUDA_VISIBLE_DEVICES": str(gpu),
        "PYTORCH_ALLOC_CONF": "expandable_segments:True",
        "PYTHONPATH": os.pathsep.join(
            [str(RACINE_PROJET), os.environ.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep),
    }
    with open(dossier / "train.log", "wb") as journal:
        processus = subprocess.Popen(
            [sys.executable, str(SCRIPT_ENTRAINEMENT), "--dossier", str(dossier)],
            stdout=journal,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=environnement,
            start_new_session=True,  # session à part : survit à la fermeture de Streamlit
        )

    ecrire_json(FICHIER_RUN_EN_COURS, {"pid": processus.pid, "dossier": str(dossier)})
    return dossier


# ---------------------------------------------------------------------------
# Suivi
# ---------------------------------------------------------------------------

def processus_vivant(pid: int) -> bool:
    """Indique si le processus d'entraînement tourne encore."""
    try:
        # Récolte le processus s'il est terminé (évite un processus "zombie")
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass  # ce n'est pas notre enfant (Streamlit a été relancé entre temps)

    # On vérifie le nom du script, au cas où le PID serait réutilisé par un autre
    # programme. Un processus terminé a une ligne de commande vide.
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fichier:
            return SCRIPT_ENTRAINEMENT.name.encode() in fichier.read()
    except OSError:
        return False


def lire_run_en_cours():
    """
    Renvoie les informations du dernier entraînement lancé, ou None s'il n'y en a pas.

    Dictionnaire renvoyé : pid, dossier, vivant (le processus tourne encore),
    statut (contenu de status.json) et config (contenu de config.json).
    """
    infos = lire_json(FICHIER_RUN_EN_COURS)
    if infos is None:
        return None
    dossier = Path(infos["dossier"])
    return {
        "pid": infos["pid"],
        "dossier": dossier,
        "vivant": processus_vivant(infos["pid"]),
        "statut": lire_json(dossier / "status.json") or {},
        "config": lire_json(dossier / "config.json") or {},
    }


def lire_log(dossier: Path, nb_lignes: int = 20) -> str:
    """Renvoie les dernières lignes du journal de l'entraînement."""
    try:
        with open(Path(dossier) / "train.log", "rb") as fichier:
            fichier.seek(0, os.SEEK_END)
            fichier.seek(max(0, fichier.tell() - 20000))
            texte = fichier.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(texte.splitlines()[-nb_lignes:])


# ---------------------------------------------------------------------------
# Arrêt
# ---------------------------------------------------------------------------

def arreter_entrainement():
    """
    Arrête l'entraînement et libère le GPU.

    Le signal est envoyé à tout le groupe de processus : le script et les
    processus de chargement des données (workers du DataLoader).
    """
    run = lire_run_en_cours()
    if run is None or not run["vivant"]:
        return
    pid = run["pid"]

    try:
        # Sécurité : le processus doit être le chef de son propre groupe,
        # sinon on risquerait d'arrêter aussi Streamlit
        if os.getpgid(pid) != pid:
            raise RuntimeError("Le processus d'entraînement n'a pas son propre groupe.")

        # Arrêt poli d'abord, puis forcé si le processus ne répond pas sous 8 s
        os.killpg(pid, signal.SIGTERM)
        for _ in range(16):
            time.sleep(0.5)
            if not processus_vivant(pid):
                break
        else:
            os.killpg(pid, signal.SIGKILL)
            time.sleep(1)
    except ProcessLookupError:
        pass  # déjà terminé

    # Le script a été interrompu : on met à jour le statut et le run MLflow
    statut = run["statut"]
    ecrire_json(
        run["dossier"] / "status.json",
        {**statut, "state": "stopped", "updated_at": datetime.now().isoformat()},
    )
    run_id = statut.get("run_id")
    if run_id:
        try:
            from mlflow.tracking import MlflowClient

            MlflowClient(MLFLOW_URI).set_terminated(run_id, status="KILLED")
        except Exception:
            pass  # le run restera affiché comme actif dans MLflow, sans autre conséquence


def oublier_run():
    """Retire l'entraînement terminé de l'écran de suivi (ses fichiers sont conservés)."""
    run = lire_run_en_cours()
    if run is not None and not run["vivant"]:
        FICHIER_RUN_EN_COURS.unlink(missing_ok=True)