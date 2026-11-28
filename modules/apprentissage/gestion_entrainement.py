"""
modules/apprentissage/gestion_entrainement.py

Lancement, suivi et arrêt de l'entraînement, sans interface Streamlit.

L'application ne lance aucun calcul : elle dépose une demande (un "job")
dans la file d'attente MongoDB (modules/jobs.py). Le worker (worker.py)
lance alors le script d'entraînement (entrainement/fastflow_mlflow.py) dans
un processus indépendant : il continue de tourner même si l'application est
fermée ou redémarrée.

Deux sources d'information, réunies par lire_run_en_cours :
  - MongoDB : l'état du job (en attente, en cours, terminé, erreur...) ;
  - les fichiers du run, écrits par le worker et par le script :

    entrainements/runs/<date>/config.json   : configuration envoyée au script
    entrainements/runs/<date>/status.json   : état écrit par le script à chaque époque
    entrainements/runs/<date>/train.log     : sortie du script

Ces fichiers doivent être sur un dossier que l'application et le worker
voient tous les deux.
"""

import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

from modules.config import (
    DOSSIER_ENTRAINEMENTS,
    MLFLOW_BASE_DONNEES,
    MLFLOW_DEMARRAGE_AUTO,
    MLFLOW_DOSSIER_ARTEFACTS,
    MLFLOW_HOTE,
    MLFLOW_JOURNAL_SERVEUR,
    MLFLOW_PORT,
    MLFLOW_URL_INTERNE,
    RACINE_PROJET,
)
from modules.jobs import (
    ANNULE,
    EN_ATTENTE,
    ERREUR,
    ETATS_NON_FINIS,
    INTERROMPU,
    TYPE_ENTRAINEMENT,
    creer_job,
    demander_arret,
    dernier_job,
    existe_job_actif,
    get_jobs_collection,
    masquer_job,
)

# Script d'entraînement (avec hsi_datamodule.py et dataloader_patches.py à côté)
SCRIPT_ENTRAINEMENT = (
    RACINE_PROJET / "modules" / "apprentissage" / "entrainement" / "fastflow_mlflow.py"
)

# Dossier des runs (le dossier "entrainements" est défini dans modules/config.py)
DOSSIER_RUNS = DOSSIER_ENTRAINEMENTS / "runs"

# Serveur MLflow : adresse utilisée par le worker et les scripts. Le lien
# affiché à l'utilisateur est une autre adresse (MLFLOW_URL_PUBLIQUE).
MLFLOW_URI = MLFLOW_URL_INTERNE

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
    """
    Démarre le serveur MLflow s'il n'est pas déjà lancé (il survit à l'application).

    Ne fait rien si MLFLOW_DEMARRAGE_AUTO vaut 0 dans le .env : MLflow est
    alors lancé à part (par exemple dans son propre container).
    """
    if not MLFLOW_DEMARRAGE_AUTO or mlflow_actif():
        return

    DOSSIER_ENTRAINEMENTS.mkdir(parents=True, exist_ok=True)
    commande = [
        sys.executable, "-m", "mlflow", "server",
        "--host", MLFLOW_HOTE,
        "--port", str(MLFLOW_PORT),
        "--backend-store-uri", f"sqlite:///{MLFLOW_BASE_DONNEES}",
        "--artifacts-destination", str(MLFLOW_DOSSIER_ARTEFACTS),
    ]
    with open(MLFLOW_JOURNAL_SERVEUR, "ab") as journal:
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


def lancer_entrainement(dataset, config: dict, gpu: int, utilisateur=None):
    """
    Dépose une demande d'entraînement dans la file d'attente et renvoie
    l'identifiant du job.

    dataset     : chemin du dataset choisi à l'étape 1
    config      : configuration validée à l'étape Paramétrage
    gpu         : indice du GPU choisi
    utilisateur : nom de l'utilisateur qui lance l'entraînement (facultatif)

    C'est le worker qui lance le script, dès qu'il est disponible. Les
    vérifications rapides (CSV présents, configuration valide) sont faites
    ici pour que l'utilisateur voie l'erreur tout de suite.

    Lève RuntimeError si un entraînement est déjà en attente ou en cours,
    et FileNotFoundError si un CSV est introuvable.
    """
    jobs = get_jobs_collection()

    if existe_job_actif(jobs, TYPE_ENTRAINEMENT):
        raise RuntimeError("Un entraînement est déjà en attente ou en cours.")

    # Les CSV d'entraînement, et de validation seulement si elle est activée,
    # doivent exister (sinon FileNotFoundError)
    format_patches = config["format_patches"]
    fraction = config["fraction_csv"]
    chemin_csv(dataset, config["split"], format_patches, fraction)
    if config["parametres_generaux"]["validation"]:
        chemin_csv(dataset, "val", format_patches, fraction)

    # La configuration est enregistrée dans MongoDB : on la réduit à des types
    # simples en la faisant passer par JSON (les tuples deviennent des listes).
    # Elle devra de toute façon être écrite en JSON pour le script.
    config_simple = json.loads(json.dumps(config))

    parametres = {"dataset": str(dataset), "config": config_simple}
    return creer_job(
        jobs, TYPE_ENTRAINEMENT, parametres, utilisateur=utilisateur, gpu=gpu
    )


# ---------------------------------------------------------------------------
# Suivi
# ---------------------------------------------------------------------------

def lire_run_en_cours():
    """
    Renvoie les informations du dernier entraînement lancé, ou None s'il n'y
    en a pas (ou si l'utilisateur l'a retiré avec oublier_run).

    Dictionnaire renvoyé :
        job_id        : identifiant du job dans MongoDB
        pid           : numéro du processus (côté worker)
        dossier       : dossier du run, ou None tant que le worker n'a pas
                        démarré le job
        vivant        : True si l'entraînement attend ou tourne
        en_attente    : True tant que le worker n'a pas démarré le job
        arret_demande : True si l'utilisateur a demandé l'arrêt
        etat_job      : état du job dans MongoDB
        statut        : contenu de status.json, complété avec l'état du job
        config        : contenu de config.json (ou la configuration demandée
                        si le run n'a pas encore démarré)
    """
    jobs = get_jobs_collection()
    job = dernier_job(jobs, TYPE_ENTRAINEMENT)
    if job is None or job.get("masque"):
        return None

    etat = job["etat"]
    dossier = Path(job["dossier"]) if job.get("dossier") else None

    # Fichiers écrits par le worker et le script (absents tant que le job attend)
    statut = (lire_json(dossier / "status.json") if dossier else None) or {}
    config = (lire_json(dossier / "config.json") if dossier else None) or job["parametres"].get("config", {})

    # L'état du job complète ce que dit le script
    if etat == EN_ATTENTE:
        statut = {"state": "starting"}
    elif etat == ANNULE:
        # Aussi pour un entraînement annulé avant de démarrer (pas de status.json)
        statut = {**statut, "state": "stopped"}
    elif etat in (ERREUR, INTERROMPU) and not statut.get("message"):
        statut = {**statut, "message": job.get("message", "")}

    return {
        "job_id": job["_id"],
        "pid": job.get("pid"),
        "dossier": dossier,
        "vivant": etat in ETATS_NON_FINIS,
        "en_attente": etat == EN_ATTENTE,
        "arret_demande": bool(job.get("arret_demande")),
        "etat_job": etat,
        "statut": statut,
        "config": config,
    }


def lire_log(dossier, nb_lignes: int = 20) -> str:
    """
    Renvoie les dernières lignes du journal de l'entraînement.

    Renvoie un texte vide si le dossier est None (job pas encore démarré)
    ou si le journal n'existe pas.
    """
    if dossier is None:
        return ""
    try:
        with open(Path(dossier) / "train.log", "rb") as fichier:
            fichier.seek(0, os.SEEK_END)
            fichier.seek(max(0, fichier.tell() - 20000))
            texte = fichier.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
    return "\n".join(texte.splitlines()[-nb_lignes:])

# Marqueurs des lignes écrites par le script d'entraînement. Les autres lignes
# (avertissements des bibliothèques, traceback...) sont masquées dans la vue épurée.
MARQUEURS_JOURNAL = ("[INFO]", "[WARN]", "[ERREUR]", "[Epoch")


def lire_log_filtre(dossier, nb_lignes: int = 20, arret_demande: bool = False) -> str:
    """
    Renvoie les dernières lignes utiles du journal de l'entraînement.

    Seules les lignes écrites par le script d'entraînement sont gardées
    (étapes, époques, enregistrements MLflow, erreurs).

    Si arret_demande vaut True, la ligne d'erreur provoquée par l'arrêt
    est remplacée par un message simple.

    Renvoie un texte vide si le dossier est None (job pas encore démarré)
    ou si le journal n'existe pas.
    """
    if dossier is None:
        return ""
    try:
        texte = (Path(dossier) / "train.log").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""

    # On garde une ligne seulement si elle contient l'un des marqueurs
    lignes_utiles = []
    for ligne in texte.splitlines():
        if any(marqueur in ligne for marqueur in MARQUEURS_JOURNAL):
            if arret_demande and "[ERREUR]" in ligne:
                # On garde ce qui précède le marqueur (l'heure) et on change le texte
                ligne = ligne.split("[ERREUR]")[0] + "[INFO] Arrêt demandé par l'utilisateur"
            lignes_utiles.append(ligne)
    return "\n".join(lignes_utiles[-nb_lignes:])

# ---------------------------------------------------------------------------
# Arrêt
# ---------------------------------------------------------------------------

def arreter_entrainement():
    """
    Demande l'arrêt de l'entraînement en attente ou en cours.

    Un entraînement en attente est annulé tout de suite. Pour un entraînement
    en cours, c'est le worker qui arrête le script dans les secondes qui
    suivent (arrêt poli, puis forcé), libère le GPU et clôture le run MLflow.
    """
    jobs = get_jobs_collection()
    job = dernier_job(jobs, TYPE_ENTRAINEMENT)
    if job is not None:
        demander_arret(jobs, job["_id"])


def oublier_run():
    """
    Retire l'entraînement terminé de l'écran de suivi.

    Son job et ses fichiers sont conservés. Sans effet si l'entraînement
    attend ou tourne encore.
    """
    jobs = get_jobs_collection()
    job = dernier_job(jobs, TYPE_ENTRAINEMENT)
    if job is not None:
        masquer_job(jobs, job["_id"])