"""
worker.py

Le "worker" exécute les traitements lourds (patching et entraînement) à la
place de l'application Streamlit.

Comment ça marche :
  1. L'application dépose une demande (un "job") dans la collection MongoDB
     "jobs" (voir modules/jobs.py).
  2. Le worker regarde la file d'attente en boucle. Dès qu'il trouve un job,
     il le réserve, puis lance le bon script dans un processus à part.
  3. Pendant que le script tourne, le worker surveille deux choses : la fin
     du script, et une éventuelle demande d'arrêt de l'utilisateur.
  4. À la fin, le worker note l'état final du job dans MongoDB.

Les scripts eux-mêmes (data_utils.py et fastflow_mlflow.py) ne changent pas :
ils continuent d'écrire leur avancement dans des fichiers JSON, que
l'application lit comme avant.

Lancement (depuis la racine du projet, avec le même environnement Python
que celui de l'application, plus les bibliothèques d'apprentissage) :

    python worker.py

Pour l'arrêter proprement : Ctrl+C.

Ce worker traite UN job à la fois, dans l'ordre d'arrivée.
"""

import os
import signal
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from pymongo.errors import PyMongoError

from modules.apprentissage.etape_patching import (
    CONFIG_FORMATS,
    DOSSIER_SUIVI,
    PYTHON_PATCHING,
    SCRIPT_PATCHING,
    chemin_journal,
    chemin_suivi,
    ecrire_suivi_local,
    lire_suivi,
)
from modules.apprentissage.gestion_entrainement import (
    DOSSIER_PATCHING,
    DOSSIER_RUNS,
    MLFLOW_URI,
    RACINE_PROJET,
    SCRIPT_ENTRAINEMENT,
    chemin_csv,
    demarrer_mlflow,
    ecrire_json,
    lire_json,
)
from modules.jobs import (
    ANNULE,
    ERREUR,
    INTERROMPU,
    TERMINE,
    TYPE_ENTRAINEMENT,
    TYPE_PATCHING,
    arret_est_demande,
    get_jobs_collection,
    marquer_interrompus,
    mettre_a_jour,
    reserver_prochain_job,
    terminer_job,
)

# Secondes entre deux regards sur la file d'attente quand elle est vide
INTERVALLE_FILE = 2

# Secondes entre deux vérifications d'un job qui tourne
INTERVALLE_SURVEILLANCE = 2

# Secondes laissées à un script pour s'arrêter poliment avant de le forcer
DELAI_ARRET_POLI = 8


# ---------------------------------------------------------------------------
# Lancement d'un processus
# ---------------------------------------------------------------------------

def lancer_processus(commande: list, fichier_journal, environnement=None):
    """
    Lance une commande dans un processus indépendant et renvoie ce processus.

    - Tout ce que la commande affiche (messages et erreurs) est écrit dans
      fichier_journal.
    - Le processus a sa propre "session" : on peut ainsi l'arrêter en bloc,
      avec les sous-processus qu'il crée (par exemple ceux qui chargent les
      données pendant l'entraînement), sans toucher au worker.
    """
    Path(fichier_journal).parent.mkdir(parents=True, exist_ok=True)
    with open(fichier_journal, "wb") as journal:
        return subprocess.Popen(
            commande,
            stdout=journal,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=environnement,
            start_new_session=True,
        )


def arreter_processus(processus):
    """
    Arrête un processus lancé par lancer_processus, avec tout son groupe.

    On demande poliment (SIGTERM). Si le processus n'a pas fini au bout de
    DELAI_ARRET_POLI secondes, on le force (SIGKILL).
    """
    try:
        # Le processus est le chef de son groupe : son numéro est celui du groupe
        os.killpg(processus.pid, signal.SIGTERM)
        debut = time.time()
        while processus.poll() is None:
            if time.time() - debut > DELAI_ARRET_POLI:
                os.killpg(processus.pid, signal.SIGKILL)
                break
            time.sleep(0.2)
        processus.wait()
    except ProcessLookupError:
        pass  # le processus était déjà terminé


# ---------------------------------------------------------------------------
# Préparation du patching
# ---------------------------------------------------------------------------

def lancer_patching_job(job: dict):
    """
    Lance le script de patching pour ce job.

    Paramètres attendus dans job["parametres"] :
        chemin_dataset : chemin du dataset à patcher
        splits         : liste des splits (par exemple ["Train", "Val"])
        noms_formats   : noms des formats choisis dans le catalogue
        full_width     : True pour des patches sur toute la largeur

    Renvoie (processus, infos), où infos est un dictionnaire à enregistrer
    dans le job.
    """
    parametres = job["parametres"]
    chemin_dataset = parametres["chemin_dataset"]

    DOSSIER_SUIVI.mkdir(parents=True, exist_ok=True)

    # Le suivi d'un ancien patching de ce dataset ne doit pas être pris pour
    # celui de ce job : l'interface lit ce fichier pendant que le job tourne
    chemin_suivi(chemin_dataset).unlink(missing_ok=True)

    commande = [
        PYTHON_PATCHING, str(SCRIPT_PATCHING),
        "--dataset", str(chemin_dataset),
        "--config", str(CONFIG_FORMATS),
        "--splits", *[s.lower() for s in parametres["splits"]],
        "--formats", *parametres["noms_formats"],
        "--suivi", str(chemin_suivi(chemin_dataset)),
    ]
    if parametres.get("full_width"):
        commande.append("--full-width")

    fichier_journal = chemin_journal(chemin_dataset)
    processus = lancer_processus(commande, fichier_journal)

    # Le script met plusieurs secondes à démarrer (imports). En attendant qu'il
    # écrive son propre suivi, on en écrit un premier, pour que l'interface
    # n'affiche pas l'avancement d'un ancien patching.
    ecrire_suivi_local(chemin_dataset, {
        "etat": "en cours",
        "format": "",
        "splits": list(parametres["splits"]),
        "cubes_total": 0,
        "cubes_faits": 0,
        "cube_courant": "",
        "message": "",
        "pid": processus.pid,
        "debut": datetime.now().isoformat(timespec="seconds"),
    })

    return processus, {"journal": str(fichier_journal)}


def noter_annulation_patching(job: dict):
    """Note "annule" dans le fichier de suivi du patching (lu par l'interface)."""
    chemin_dataset = job["parametres"]["chemin_dataset"]
    suivi = lire_suivi(chemin_dataset)
    if suivi is None:
        return
    suivi["etat"] = "annule"
    suivi["message"] = "Patching annulé par l'utilisateur."
    ecrire_suivi_local(chemin_dataset, suivi)


# ---------------------------------------------------------------------------
# Préparation de l'entraînement
# ---------------------------------------------------------------------------

def lancer_entrainement_job(job: dict):
    """
    Lance le script d'entraînement pour ce job.

    Paramètres attendus dans job["parametres"] :
        dataset : chemin du dataset choisi à l'étape 1
        config  : configuration validée à l'étape Paramétrage
    Le numéro du GPU est lu dans job["gpu"].

    Renvoie (processus, infos), où infos est un dictionnaire à enregistrer
    dans le job (dossier du run et journal).
    """
    parametres = job["parametres"]
    dataset = parametres["dataset"]
    config = parametres["config"]
    gpu = job.get("gpu")
    if gpu is None:
        raise ValueError("Aucun GPU n'a été choisi pour l'entraînement.")

    # CSV d'entraînement, et de validation seulement si elle est activée
    format_patches = config["format_patches"]
    fraction = config["fraction_csv"]
    csv = {"train": str(chemin_csv(dataset, config["split"], format_patches, fraction))}
    if config["parametres_generaux"]["validation"]:
        csv["val"] = str(chemin_csv(dataset, "val", format_patches, fraction))

    # En local (sans Docker), le worker démarre MLflow s'il n'est pas lancé.
    # Avec Docker, MLflow aura son propre container et cette ligne disparaîtra.
    demarrer_mlflow()

    # Un dossier par entraînement
    dossier = DOSSIER_RUNS / datetime.now().strftime("%Y%m%d_%H%M%S")
    dossier.mkdir(parents=True)

    # Ce fichier est lu par le script : configuration, chemins et GPU
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

    # Le script ne voit que le GPU choisi (CUDA_VISIBLE_DEVICES).
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
    fichier_journal = dossier / "train.log"
    processus = lancer_processus(
        [sys.executable, str(SCRIPT_ENTRAINEMENT), "--dossier", str(dossier)],
        fichier_journal,
        environnement,
    )
    return processus, {"dossier": str(dossier), "journal": str(fichier_journal)}


def noter_arret_entrainement(job: dict):
    """
    Après un arrêt demandé : met à jour status.json et clôture le run MLflow.

    Sans cela, le run resterait affiché comme "en cours" dans MLflow.
    """
    dossier = job.get("dossier")
    if not dossier:
        return
    dossier = Path(dossier)

    statut = lire_json(dossier / "status.json") or {}
    ecrire_json(
        dossier / "status.json",
        {**statut, "state": "stopped", "updated_at": datetime.now().isoformat()},
    )

    run_id = statut.get("run_id")
    if run_id:
        try:
            from mlflow.tracking import MlflowClient

            MlflowClient(MLFLOW_URI).set_terminated(run_id, status="KILLED")
        except Exception:
            pass  # le run restera affiché comme actif dans MLflow, sans autre conséquence


# ---------------------------------------------------------------------------
# Surveillance et exécution d'un job
# ---------------------------------------------------------------------------

def surveiller(collection, job_id, processus):
    """
    Attend la fin du processus en surveillant la demande d'arrêt.

    Toutes les INTERVALLE_SURVEILLANCE secondes :
      - on rafraîchit la "dernière activité" du job (preuve que le worker vit) ;
      - on regarde si l'utilisateur a demandé l'arrêt.

    Renvoie (résultat, code), où résultat vaut TERMINE, ERREUR ou ANNULE
    et code est le code de sortie du script (0 = tout s'est bien passé).
    """
    while processus.poll() is None:
        mettre_a_jour(collection, job_id)

        if arret_est_demande(collection, job_id):
            arreter_processus(processus)
            return ANNULE, processus.returncode

        time.sleep(INTERVALLE_SURVEILLANCE)

    code = processus.returncode
    return (TERMINE if code == 0 else ERREUR), code


def executer_job(collection, job: dict):
    """Exécute un job réservé : lance le script, le surveille, note le résultat."""
    job_id = job["_id"]

    # --- 1. Lancement ---
    try:
        if job["type"] == TYPE_PATCHING:
            processus, infos = lancer_patching_job(job)
        elif job["type"] == TYPE_ENTRAINEMENT:
            processus, infos = lancer_entrainement_job(job)
        else:
            raise ValueError(f"Type de job inconnu : {job['type']}")
    except Exception as erreur:
        traceback.print_exc()
        terminer_job(collection, job_id, ERREUR, f"Impossible de lancer le calcul : {erreur}")
        return

    # On garde le numéro du processus et les chemins utiles dans le job
    mettre_a_jour(collection, job_id, pid=processus.pid, **infos)
    job = {**job, **infos}

    # --- 2. Surveillance ---
    try:
        resultat, code = surveiller(collection, job_id, processus)
    except KeyboardInterrupt:
        # Le worker lui-même est arrêté (Ctrl+C ou arrêt du container)
        arreter_processus(processus)
        terminer_job(collection, job_id, INTERROMPU, "Le worker a été arrêté.")
        raise

    # --- 3. Résultat ---
    if resultat == ANNULE:
        if job["type"] == TYPE_PATCHING:
            noter_annulation_patching(job)
        else:
            noter_arret_entrainement(job)
        terminer_job(collection, job_id, ANNULE, "Arrêté à la demande de l'utilisateur.")
    elif resultat == TERMINE:
        terminer_job(collection, job_id, TERMINE, "Traitement terminé.")
    else:
        terminer_job(
            collection, job_id, ERREUR,
            f"Le script s'est arrêté avec une erreur (code {code}). Voir le journal.",
        )


def traiter_un_job(collection) -> bool:
    """
    Réserve le prochain job en attente et l'exécute.

    Renvoie True si un job a été traité, False si la file était vide.
    """
    job = reserver_prochain_job(collection)
    if job is None:
        return False
    print(f"[worker] Job {job['_id']} ({job['type']}) : démarrage", flush=True)
    executer_job(collection, job)
    print(f"[worker] Job {job['_id']} : terminé", flush=True)
    return True


# ---------------------------------------------------------------------------
# Programme principal
# ---------------------------------------------------------------------------

def arret_propre(numero_signal, cadre):
    """
    Appelée quand le worker reçoit SIGTERM (par exemple "docker stop").

    On la transforme en KeyboardInterrupt, comme Ctrl+C : le code qui gère
    déjà Ctrl+C s'occupe ainsi aussi de l'arrêt du container.
    """
    raise KeyboardInterrupt


def main():
    """Boucle principale du worker."""
    # Les scripts sont désignés par des chemins relatifs à la racine du projet
    os.chdir(RACINE_PROJET)
    signal.signal(signal.SIGTERM, arret_propre)

    collection = get_jobs_collection()

    # Les jobs restés "en cours" appartiennent à un ancien worker arrêté
    nombre = marquer_interrompus(collection)
    if nombre:
        print(f"[worker] {nombre} job(s) marqué(s) comme interrompu(s).", flush=True)

    print("[worker] En attente de jobs (Ctrl+C pour arrêter).", flush=True)
    try:
        while True:
            try:
                travail_fait = traiter_un_job(collection)
            except PyMongoError as erreur:
                # MongoDB est injoignable : on attend un peu puis on réessaie
                print(f"[worker] Problème avec MongoDB : {erreur}", flush=True)
                time.sleep(5)
                continue

            if not travail_fait:
                time.sleep(INTERVALLE_FILE)
    except KeyboardInterrupt:
        print("[worker] Arrêt du worker.", flush=True)


if __name__ == "__main__":
    main()