"""
modules/etat_gpus.py

État des GPU du serveur, partagé entre le worker et l'application par MongoDB.

Pourquoi : la commande nvidia-smi doit être lancée là où sont les GPU, c'est
à dire par le worker. L'application, qui peut tourner dans un autre container
sans GPU, ne peut pas la lancer elle-même. Le worker relève donc l'état des
GPU toutes les quelques secondes et le publie dans MongoDB (collection
"etat_worker", un seul document). L'application lit ce document.

La date de la dernière publication indique aussi si le worker est en vie :
si elle est trop ancienne, le worker est arrêté ou en panne.

Ce module n'importe jamais Streamlit. Comme dans modules/jobs.py, les
fonctions reçoivent la collection en premier argument (une fausse collection
mongomock dans les tests).
"""

import subprocess
from datetime import datetime, timezone

from pymongo.collection import Collection

from modules.db_mongo import get_db

# Collection où le worker publie son état, et identifiant du document qui
# contient l'état des GPU
NOM_COLLECTION_ETAT_WORKER = "etat_worker"
ID_DOCUMENT_GPUS = "gpus"

# Au bout de ce nombre de secondes sans publication, le worker est considéré
# comme arrêté. C'est volontairement long : le worker ne publie pas pendant
# qu'il attend le démarrage de MLflow (jusqu'à 20 secondes).
DELAI_WORKER_ACTIF = 60


def get_etat_worker_collection() -> Collection:
    """Retourne la collection "etat_worker" de la base de données."""
    return get_db()[NOM_COLLECTION_ETAT_WORKER]


# ---------------------------------------------------------------------------
# Côté worker : lire nvidia-smi et publier
# ---------------------------------------------------------------------------

def analyser_sortie_nvidia_smi(sortie: str) -> list:
    """
    Transforme la sortie de nvidia-smi en liste de GPU.

    Chaque ligne a la forme "index, utilisation, mémoire utilisée, mémoire
    totale", avec les mémoires en Mo. Par exemple : "1, 87, 20480, 24576".
    Les mémoires sont converties en Go. Lève ValueError si une ligne est
    mal formée.
    """
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


def interroger_gpus() -> list:
    """
    Interroge nvidia-smi et renvoie l'état des GPU de cet ordinateur.

    La liste est vide si aucun GPU n'est détecté (nvidia-smi absent, en
    erreur ou trop lent).
    """
    try:
        sortie = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True, text=True, timeout=5, check=True,
        ).stdout
        return analyser_sortie_nvidia_smi(sortie)
    except (OSError, subprocess.SubprocessError, ValueError):
        return []


def publier_etat_gpus(collection, gpus: list):
    """Enregistre l'état des GPU dans MongoDB, à la place du précédent."""
    collection.replace_one(
        {"_id": ID_DOCUMENT_GPUS},
        {
            "_id": ID_DOCUMENT_GPUS,
            "gpus": gpus,
            "maj_le": datetime.now(timezone.utc),
        },
        upsert=True,
    )


# ---------------------------------------------------------------------------
# Côté application : lire
# ---------------------------------------------------------------------------

def lire_etat_gpus(collection) -> dict:
    """
    Renvoie l'état des GPU publié par le worker.

    Dictionnaire renvoyé :
        gpus          : liste des GPU (vide si aucun n'est détecté)
        worker_actif  : False si le worker n'a jamais publié, ou s'il n'a
                        rien publié depuis DELAI_WORKER_ACTIF secondes
        age_secondes  : ancienneté du relevé en secondes (None s'il n'y en a pas)

    Si le worker n'est pas actif, la liste des GPU est vide : l'état connu
    n'est plus fiable.
    """
    document = collection.find_one({"_id": ID_DOCUMENT_GPUS})
    if document is None:
        return {"gpus": [], "worker_actif": False, "age_secondes": None}

    publie_le = document["maj_le"]
    # MongoDB renvoie des dates sans fuseau horaire : ce sont des dates UTC
    if publie_le.tzinfo is None:
        publie_le = publie_le.replace(tzinfo=timezone.utc)
    age = max(0, int((datetime.now(timezone.utc) - publie_le).total_seconds()))

    worker_actif = age <= DELAI_WORKER_ACTIF
    return {
        "gpus": document["gpus"] if worker_actif else [],
        "worker_actif": worker_actif,
        "age_secondes": age,
    }