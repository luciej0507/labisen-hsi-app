"""
modules/jobs.py

File d'attente des traitements lourds (patching et entraînement), stockée
dans la collection MongoDB "jobs".

Principe : l'application Streamlit ne lance plus aucun calcul. Elle dépose
une demande (un "job") dans cette collection. Un programme séparé, le
worker (worker.py), lit les demandes, exécute les calculs et met à jour
l'état de chaque job. L'application lit cet état pour l'afficher.

Cycle de vie d'un job :

    "en attente"  ->  "en cours"  ->  "termine"
                                  ->  "erreur"
                                  ->  "annule"      (arrêt demandé par l'utilisateur)
                                  ->  "interrompu"  (le worker s'est arrêté en route)

Ce module n'importe jamais Streamlit, pour que chaque fonction puisse être
testée avec un simple assert. Comme dans modules/comptes/users.py, les
fonctions reçoivent la collection en premier argument : en production on
passe get_jobs_collection(), dans les tests une fausse collection mongomock.
"""

from datetime import datetime, timezone
from typing import Optional

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, DESCENDING, ReturnDocument
from pymongo.collection import Collection

from modules.db_mongo import get_db

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Types de job
TYPE_PATCHING = "patching"
TYPE_ENTRAINEMENT = "entrainement"
TYPES = (TYPE_PATCHING, TYPE_ENTRAINEMENT)

# États d'un job (mêmes mots que ceux déjà utilisés par l'interface)
EN_ATTENTE = "en attente"
EN_COURS = "en cours"
TERMINE = "termine"
ERREUR = "erreur"
ANNULE = "annule"
INTERROMPU = "interrompu"

# Un job qui n'est pas fini : il attend ou il tourne
ETATS_NON_FINIS = (EN_ATTENTE, EN_COURS)

# États finaux : le job ne changera plus
ETATS_FINAUX = (TERMINE, ERREUR, ANNULE, INTERROMPU)


# ---------------------------------------------------------------------------
# Petits utilitaires
# ---------------------------------------------------------------------------

def get_jobs_collection() -> Collection:
    """Retourne la collection "jobs" de la base de données."""
    return get_db()["jobs"]


def maintenant() -> datetime:
    """Renvoie la date et l'heure actuelles (en UTC, comme dans users.py)."""
    return datetime.now(timezone.utc)


def _identifiant(job_id) -> Optional[ObjectId]:
    """
    Convertit un identifiant de job en ObjectId.

    L'identifiant peut arriver sous forme de texte (par exemple depuis
    st.session_state). Renvoie None si le texte n'est pas un identifiant valide.
    """
    if isinstance(job_id, ObjectId):
        return job_id
    try:
        return ObjectId(str(job_id))
    except (InvalidId, TypeError):
        return None


# ---------------------------------------------------------------------------
# Création et lecture (côté application)
# ---------------------------------------------------------------------------

def creer_job(jobs, type_job: str, parametres: dict, utilisateur=None, gpu=None, cle=None):
    """
    Dépose une nouvelle demande dans la file d'attente et renvoie son identifiant.

    type_job    : TYPE_PATCHING ou TYPE_ENTRAINEMENT
    parametres  : tout ce dont le worker a besoin pour lancer le calcul
                  (dictionnaire simple : textes, nombres, listes)
    utilisateur : nom de l'utilisateur qui a lancé la demande (facultatif)
    gpu         : numéro du GPU demandé (facultatif)
    cle         : texte qui identifie la cible du job, par exemple le chemin
                  du dataset. Sert à retrouver le job d'un dataset donné.
    """
    if type_job not in TYPES:
        raise ValueError(f"Type de job inconnu : {type_job}")

    maintenant_ = maintenant()
    document = {
        "type": type_job,
        "etat": EN_ATTENTE,
        "parametres": parametres,
        "utilisateur": utilisateur,
        "gpu": gpu,
        "cle": cle,
        # Mis à True par l'application quand l'utilisateur clique sur "Arrêter"
        "arret_demande": False,
        # Mis à True quand l'utilisateur masque le résultat d'un job fini
        # (le job reste en base, mais l'interface ne l'affiche plus)
        "masque": False,
        "message": "",
        # Renseignés par le worker quand le job démarre
        "pid": None,
        "dossier": None,
        # Dates
        "cree_le": maintenant_,
        "demarre_le": None,
        "termine_le": None,
        # "Dernière activité" : le worker la rafraîchit régulièrement
        "maj_le": maintenant_,
    }
    return jobs.insert_one(document).inserted_id


def lire_job(jobs, job_id) -> Optional[dict]:
    """Renvoie un job à partir de son identifiant, ou None s'il n'existe pas."""
    identifiant = _identifiant(job_id)
    if identifiant is None:
        return None
    return jobs.find_one({"_id": identifiant})


def dernier_job(jobs, type_job: str, cle=None) -> Optional[dict]:
    """
    Renvoie le job le plus récent d'un type, ou None s'il n'y en a pas.

    Si "cle" est donnée (par exemple le chemin d'un dataset), seuls les jobs
    de cette cible sont regardés.
    """
    filtre = {"type": type_job}
    if cle is not None:
        filtre["cle"] = cle
    return jobs.find_one(filtre, sort=[("cree_le", DESCENDING), ("_id", DESCENDING)])


def dernier_job_visible(jobs, type_job: str, cle=None) -> Optional[dict]:
    """
    Renvoie le job le plus récent, sauf si l'utilisateur l'a masqué.

    Renvoie None s'il n'y a aucun job, ou si le plus récent est masqué.
    On ne remonte jamais à un job plus ancien : sinon, masquer le résultat
    du dernier job ferait réapparaître celui d'avant.
    """
    job = dernier_job(jobs, type_job, cle)
    if job is None or job.get("masque"):
        return None
    return job


def masquer_job(jobs, job_id) -> bool:
    """
    Masque le résultat d'un job fini. Renvoie True si le job a été masqué.

    Un job qui attend ou qui tourne ne peut pas être masqué.
    """
    identifiant = _identifiant(job_id)
    if identifiant is None:
        return False
    resultat = jobs.update_one(
        {"_id": identifiant, "etat": {"$in": list(ETATS_FINAUX)}},
        {"$set": {"masque": True}},
    )
    return resultat.matched_count > 0


def existe_job_actif(jobs, type_job: str, cle=None) -> bool:
    """
    Indique si un job de ce type attend ou tourne encore.

    Sert à empêcher de lancer deux traitements en même temps sur la même cible.
    """
    filtre = {"type": type_job, "etat": {"$in": list(ETATS_NON_FINIS)}}
    if cle is not None:
        filtre["cle"] = cle
    return jobs.count_documents(filtre, limit=1) > 0


def lister_jobs(jobs, type_job=None, etats=None, limite: int = 50, utilisateur=None) -> list:
    """
    Renvoie les jobs les plus récents en premier.

    type_job    : ne garder que ce type (facultatif)
    etats       : ne garder que ces états, par exemple (EN_COURS,) (facultatif)
    limite      : nombre maximum de jobs renvoyés
    utilisateur : ne garder que les jobs de cet utilisateur (facultatif)
    """
    filtre = {}
    if type_job is not None:
        filtre["type"] = type_job
    if etats is not None:
        filtre["etat"] = {"$in": list(etats)}
    if utilisateur is not None:
        filtre["utilisateur"] = utilisateur
    curseur = jobs.find(filtre).sort([("cree_le", DESCENDING), ("_id", DESCENDING)])
    return list(curseur.limit(limite))


# ---------------------------------------------------------------------------
# Arrêt (côté application)
# ---------------------------------------------------------------------------

def demander_arret(jobs, job_id) -> bool:
    """
    Demande l'arrêt d'un job. Renvoie True si la demande a été prise en compte.

    - Un job "en attente" n'a pas encore démarré : il est annulé tout de suite.
    - Un job "en cours" reçoit une demande d'arrêt : c'est le worker qui
      arrêtera le calcul, puis passera le job à l'état "annule".
    - Un job déjà fini ne change pas (la fonction renvoie False).
    """
    identifiant = _identifiant(job_id)
    if identifiant is None:
        return False

    # Cas 1 : le job n'a pas démarré, on l'annule directement
    resultat = jobs.update_one(
        {"_id": identifiant, "etat": EN_ATTENTE},
        {"$set": {
            "etat": ANNULE,
            "message": "Annulé avant le démarrage.",
            "termine_le": maintenant(),
        }},
    )
    if resultat.matched_count > 0:
        return True

    # Cas 2 : le job tourne, on pose la demande d'arrêt pour le worker
    resultat = jobs.update_one(
        {"_id": identifiant, "etat": EN_COURS},
        {"$set": {"arret_demande": True}},
    )
    return resultat.matched_count > 0


def arret_est_demande(jobs, job_id) -> bool:
    """Indique si l'utilisateur a demandé l'arrêt de ce job (lu par le worker)."""
    job = lire_job(jobs, job_id)
    return bool(job and job.get("arret_demande"))


# ---------------------------------------------------------------------------
# Exécution (côté worker)
# ---------------------------------------------------------------------------

def reserver_prochain_job(jobs) -> Optional[dict]:
    """
    Réserve le plus ancien job "en attente" et le passe à "en cours".

    Renvoie le job, ou None si la file est vide.

    La recherche et le changement d'état se font en UNE SEULE opération
    (find_one_and_update). Si deux workers tournaient en même temps, ils ne
    pourraient donc jamais prendre le même job.
    """
    maintenant_ = maintenant()
    return jobs.find_one_and_update(
        {"etat": EN_ATTENTE},
        {"$set": {"etat": EN_COURS, "demarre_le": maintenant_, "maj_le": maintenant_}},
        sort=[("cree_le", ASCENDING), ("_id", ASCENDING)],
        return_document=ReturnDocument.AFTER,
    )


def mettre_a_jour(jobs, job_id, **champs) -> bool:
    """
    Modifie des champs d'un job et rafraîchit sa "dernière activité" (maj_le).

    Exemple : mettre_a_jour(jobs, job_id, pid=1234, dossier="/chemin/du/run")
    Renvoie True si le job existe.
    """
    identifiant = _identifiant(job_id)
    if identifiant is None:
        return False
    champs["maj_le"] = maintenant()
    resultat = jobs.update_one({"_id": identifiant}, {"$set": champs})
    return resultat.matched_count > 0


def terminer_job(jobs, job_id, etat: str, message: str = "") -> bool:
    """
    Passe un job à un état final et note l'heure de fin.

    etat    : TERMINE, ERREUR, ANNULE ou INTERROMPU
    message : texte affiché à l'utilisateur (par exemple la cause d'une erreur)
    """
    if etat not in ETATS_FINAUX:
        raise ValueError(f"État final inconnu : {etat}")
    maintenant_ = maintenant()
    return mettre_a_jour(
        jobs, job_id, etat=etat, message=message, termine_le=maintenant_
    )


def marquer_interrompus(jobs) -> int:
    """
    Passe à "interrompu" tous les jobs restés "en cours". Renvoie leur nombre.

    À appeler UNE FOIS au démarrage du worker : si le worker démarre, c'est
    que l'ancien s'est arrêté, et les calculs qu'il avait lancés se sont
    arrêtés avec lui. (Cela suppose un seul worker. Avec plusieurs workers,
    il faudrait distinguer les jobs de chacun.)
    """
    maintenant_ = maintenant()
    resultat = jobs.update_many(
        {"etat": EN_COURS},
        {"$set": {
            "etat": INTERROMPU,
            "message": "Le worker s'est arrêté pendant le traitement.",
            "termine_le": maintenant_,
            "maj_le": maintenant_,
        }},
    )
    return resultat.modified_count