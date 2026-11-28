"""
modules/accueil_user.py

Données de la page Accueil de l'espace utilisateur : entraînement en cours
et historique des entraînements d'un utilisateur.

Ce module ne contient aucune interface Streamlit : l'affichage est dans
ui/accueil_user.py.
"""

from datetime import timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from modules.apprentissage.etape_lancement_suivi import etat_du_run, url_mlflow
from modules.apprentissage.gestion_entrainement import construire_run
from modules.jobs import (
    ETATS_FINAUX,
    ETATS_NON_FINIS,
    TYPE_ENTRAINEMENT,
    get_jobs_collection,
    lister_jobs,
    maintenant,
)

# Fuseau horaire des dates affichées (la base stocke des dates en UTC)
FUSEAU = ZoneInfo("Europe/Paris")


# ---------------------------------------------------------------------------
# Mise en forme
# ---------------------------------------------------------------------------

def en_utc(date):
    """Rend une date "avec fuseau" en UTC (MongoDB renvoie souvent des dates sans fuseau)."""
    if date is None:
        return None
    if date.tzinfo is None:
        return date.replace(tzinfo=timezone.utc)
    return date


def formater_date(date) -> str:
    """Renvoie une date lisible en heure de Paris, par exemple "28/11/2026 17:56"."""
    date = en_utc(date)
    if date is None:
        return "-"
    return date.astimezone(FUSEAU).strftime("%d/%m/%Y %H:%M")


def formater_duree(secondes) -> str:
    """Renvoie une durée lisible : "45 s", "12 min 05 s" ou "1 h 03 min"."""
    secondes = int(secondes)
    if secondes < 60:
        return f"{secondes} s"
    minutes, reste = divmod(secondes, 60)
    if minutes < 60:
        return f"{minutes} min {reste:02d} s"
    heures, minutes = divmod(minutes, 60)
    return f"{heures} h {minutes:02d} min"


def duree_du_job(job: dict) -> str:
    """
    Renvoie la durée du calcul d'un job (du démarrage à la fin).

    Pour un job encore en cours, la durée s'arrête à maintenant.
    Renvoie "-" si le job n'a jamais démarré (en attente ou annulé avant).
    """
    debut = en_utc(job.get("demarre_le"))
    if debut is None:
        return "-"
    fin = en_utc(job.get("termine_le")) or maintenant()
    return formater_duree((fin - debut).total_seconds())


# ---------------------------------------------------------------------------
# Lecture des entraînements
# ---------------------------------------------------------------------------

def resumer_job(job: dict) -> dict:
    """
    Prépare les informations d'un entraînement pour l'affichage.

    Dictionnaire renvoyé :
        date         : date de la demande, en heure de Paris
        dataset      : nom du dataset
        modele       : nom du modèle
        etat         : en_attente, demarrage, en_cours, termine, arrete ou erreur
        epoque       : dernière époque faite (None si inconnue)
        total_epochs : nombre d'époques prévues (None si inconnu)
        loss         : loss de la dernière époque (None si inconnue)
        gpu          : numéro du GPU demandé (None si inconnu)
        duree        : durée du calcul, déjà mise en forme
        url_mlflow   : lien vers le run dans MLflow (None si le run n'existe pas)
    """
    # Même calcul que sur l'étape 4 : l'état affiché est donc identique
    run = construire_run(job)
    statut = run["statut"]
    etat = "en_attente" if run["en_attente"] else etat_du_run(run)

    parametres = job.get("parametres", {})
    return {
        "date": formater_date(job.get("cree_le")),
        "dataset": Path(parametres.get("dataset", "-")).name,
        "modele": parametres.get("config", {}).get("modele", "-"),
        "etat": etat,
        "epoque": statut.get("epoch"),
        "total_epochs": statut.get("total_epochs"),
        "loss": statut.get("loss"),
        "gpu": job.get("gpu"),
        "duree": duree_du_job(job),
        "url_mlflow": url_mlflow(statut) if statut.get("run_id") else None,
    }


def lire_entrainement_en_cours(utilisateur):
    """
    Renvoie le résumé de l'entraînement en attente ou en cours de l'utilisateur,
    ou None s'il n'y en a pas.
    """
    # Sans nom d'utilisateur, on ne renvoie rien (jamais les jobs des autres)
    if not utilisateur:
        return None
    jobs = lister_jobs(
        get_jobs_collection(), TYPE_ENTRAINEMENT,
        etats=ETATS_NON_FINIS, limite=1, utilisateur=utilisateur,
    )
    if not jobs:
        return None
    return resumer_job(jobs[0])


def lister_historique(utilisateur, limite: int) -> list:
    """
    Renvoie les résumés des derniers entraînements terminés de l'utilisateur
    (terminés, arrêtés ou en erreur), du plus récent au plus ancien.
    """
    if not utilisateur:
        return []
    jobs = lister_jobs(
        get_jobs_collection(), TYPE_ENTRAINEMENT,
        etats=ETATS_FINAUX, limite=limite, utilisateur=utilisateur,
    )
    return [resumer_job(job) for job in jobs]