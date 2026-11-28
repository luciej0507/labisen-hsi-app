"""
tests/jobs/test_gpus.py : tests de l'état des GPU (modules/etat_gpus.py) et de
sa publication par le worker.

Aucun vrai nvidia-smi n'est lancé et aucune connexion à MongoDB n'est ouverte :
la commande est remplacée par un faux résultat, et la collection par une
fausse collection mongomock.
"""

import subprocess
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pymongo.errors import PyMongoError

import worker
from modules import etat_gpus
from modules import jobs as file_jobs
from modules.apprentissage import etape_lancement_suivi, etape_patching

SORTIE_DEUX_GPU = "0, 12, 2048, 24576, 45\n1, 87, 20480, 24576, 72\n"


@pytest.fixture
def etat(jobs):
    """La collection "etat_worker" factice, dans la même base que "jobs"."""
    return jobs.database[etat_gpus.NOM_COLLECTION_ETAT_WORKER]


# ---------------------------------------------------------------------------
# Lecture de nvidia-smi
# ---------------------------------------------------------------------------

def test_analyser_la_sortie_convertit_les_mo_en_go():
    """Chaque ligne devient un GPU, avec la mémoire en Go et la température en °C."""
    gpus = etat_gpus.analyser_sortie_nvidia_smi(SORTIE_DEUX_GPU)

    assert gpus == [
        {"index": 0, "utilisation": 12, "memoire_utilisee": 2.0,
         "memoire_totale": 24.0, "temperature": 45},
        {"index": 1, "utilisation": 87, "memoire_utilisee": 20.0,
         "memoire_totale": 24.0, "temperature": 72},
    ]


def test_analyser_une_sortie_vide_donne_une_liste_vide():
    """Sans ligne, il n'y a aucun GPU."""
    assert etat_gpus.analyser_sortie_nvidia_smi("") == []
    assert etat_gpus.analyser_sortie_nvidia_smi("\n") == []


def test_analyser_une_ligne_mal_formee_leve_une_erreur():
    """Une ligne incomplète ou illisible n'est pas ignorée en silence."""
    with pytest.raises(ValueError):
        etat_gpus.analyser_sortie_nvidia_smi("0, 12, 2048")
    # Ancien format sans la température : il manque une colonne
    with pytest.raises(ValueError):
        etat_gpus.analyser_sortie_nvidia_smi("0, 12, 2048, 24576")
    with pytest.raises(ValueError):
        etat_gpus.analyser_sortie_nvidia_smi("zero, douze, beaucoup, enormement, chaud")


def test_interroger_gpus_lit_la_sortie_de_nvidia_smi(monkeypatch):
    """interroger_gpus lance nvidia-smi et analyse sa sortie."""
    appels = []

    def faux_run(commande, **options):
        appels.append(commande)
        return SimpleNamespace(stdout=SORTIE_DEUX_GPU)

    monkeypatch.setattr(etat_gpus.subprocess, "run", faux_run)

    gpus = etat_gpus.interroger_gpus()

    assert [g["index"] for g in gpus] == [0, 1]
    assert [g["temperature"] for g in gpus] == [45, 72]
    assert appels[0][0] == "nvidia-smi"
    # La commande demande bien la température
    assert "temperature.gpu" in appels[0][1]


def test_interroger_gpus_sans_nvidia_smi_renvoie_une_liste_vide(monkeypatch):
    """Sur une machine sans GPU, nvidia-smi n'existe pas : pas d'erreur, juste aucun GPU."""
    def introuvable(commande, **options):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(etat_gpus.subprocess, "run", introuvable)

    assert etat_gpus.interroger_gpus() == []


def test_interroger_gpus_nvidia_smi_en_erreur_ou_trop_lent(monkeypatch):
    """Une erreur ou un délai dépassé donnent aussi une liste vide."""
    def en_erreur(commande, **options):
        raise subprocess.CalledProcessError(9, commande)

    def trop_lent(commande, **options):
        raise subprocess.TimeoutExpired(commande, 5)

    monkeypatch.setattr(etat_gpus.subprocess, "run", en_erreur)
    assert etat_gpus.interroger_gpus() == []

    monkeypatch.setattr(etat_gpus.subprocess, "run", trop_lent)
    assert etat_gpus.interroger_gpus() == []


def test_interroger_gpus_sortie_illisible_renvoie_une_liste_vide(monkeypatch):
    """Une sortie incompréhensible ne fait pas planter le worker."""
    monkeypatch.setattr(
        etat_gpus.subprocess, "run", lambda commande, **options: SimpleNamespace(stdout="n'importe quoi")
    )

    assert etat_gpus.interroger_gpus() == []
    
    
def test_analyser_une_temperature_inconnue_donne_none():
    """Si le GPU ne donne pas sa température, on garde None et le GPU est conservé."""
    gpus = etat_gpus.analyser_sortie_nvidia_smi("0, 12, 2048, 24576, [N/A]")

    assert gpus[0]["temperature"] is None
    assert gpus[0]["index"] == 0


# ---------------------------------------------------------------------------
# Publication et lecture
# ---------------------------------------------------------------------------

GPUS = [{"index": 0, "utilisation": 12, "memoire_utilisee": 2.0,
         "memoire_totale": 24.0, "temperature": 45}]


def test_lire_sans_publication_le_worker_est_inactif(etat):
    """Tant que le worker n'a rien publié, on le considère absent."""
    assert etat_gpus.lire_etat_gpus(etat) == {
        "gpus": [], "worker_actif": False, "age_secondes": None
    }


def test_publier_puis_lire_renvoie_les_gpu(etat):
    """Ce que le worker publie est ce que l'application lit."""
    etat_gpus.publier_etat_gpus(etat, GPUS)

    releve = etat_gpus.lire_etat_gpus(etat)

    assert releve["gpus"] == GPUS
    assert releve["worker_actif"] is True
    assert releve["age_secondes"] <= 2


def test_publier_remplace_le_releve_precedent(etat):
    """Il n'y a toujours qu'un seul document, toujours le dernier relevé."""
    etat_gpus.publier_etat_gpus(etat, GPUS)
    etat_gpus.publier_etat_gpus(etat, [])

    assert etat.count_documents({}) == 1
    assert etat_gpus.lire_etat_gpus(etat)["gpus"] == []
    assert etat_gpus.lire_etat_gpus(etat)["worker_actif"] is True


def test_un_releve_trop_ancien_signale_un_worker_arrete(etat):
    """
    Si le worker ne publie plus depuis longtemps, il est considéré arrêté, et
    les GPU connus ne sont plus renvoyés (l'état ne serait plus fiable).
    """
    etat_gpus.publier_etat_gpus(etat, GPUS)
    trop_vieux = datetime.now(timezone.utc) - timedelta(seconds=etat_gpus.DELAI_WORKER_ACTIF + 30)
    etat.update_one({"_id": etat_gpus.ID_DOCUMENT_GPUS}, {"$set": {"maj_le": trop_vieux}})

    releve = etat_gpus.lire_etat_gpus(etat)

    assert releve["worker_actif"] is False
    assert releve["gpus"] == []
    assert releve["age_secondes"] >= etat_gpus.DELAI_WORKER_ACTIF


def test_une_date_sans_fuseau_est_comprise_comme_utc(etat):
    """MongoDB renvoie des dates sans fuseau : elles sont lues comme des dates UTC."""
    maintenant_sans_fuseau = datetime.now(timezone.utc).replace(tzinfo=None)
    etat.insert_one({"_id": etat_gpus.ID_DOCUMENT_GPUS, "gpus": GPUS, "maj_le": maintenant_sans_fuseau})

    releve = etat_gpus.lire_etat_gpus(etat)

    assert releve["worker_actif"] is True
    assert releve["age_secondes"] <= 2


def test_l_interface_lit_l_etat_publie(etat, monkeypatch):
    """lire_etat_gpus de l'étape 4 renvoie ce que le worker a publié."""
    monkeypatch.setattr(etat_gpus, "get_etat_worker_collection", lambda: etat)
    etat_gpus.publier_etat_gpus(etat, GPUS)

    releve = etape_lancement_suivi.lire_etat_gpus()

    assert releve["gpus"] == GPUS
    assert releve["worker_actif"] is True
    # Les lignes du tableau et le libellé du choix restent ceux de l'étape 4
    assert etape_lancement_suivi.lignes_gpus(releve["gpus"])[0]["Température (°C)"] == 45
    assert etape_lancement_suivi.libelle_gpu(releve["gpus"][0]) == "GPU 0 (12 % utilisé)"


# ---------------------------------------------------------------------------
# Publication par le worker
# ---------------------------------------------------------------------------

@pytest.fixture
def releves(monkeypatch):
    """
    Remplace nvidia-smi par un faux relevé, compte les appels, et remet à zéro
    la mémoire du dernier relevé du worker (chaque test repart de "jamais").
    """
    compteur = []

    def faux_interroger():
        compteur.append(1)
        return GPUS

    monkeypatch.setattr(worker, "interroger_gpus", faux_interroger)
    monkeypatch.setattr(worker, "_derniere_publication", float("-inf"))
    return compteur


def test_le_worker_publie_les_gpu_dans_la_collection_d_etat(jobs, etat, releves):
    """Le worker publie dans "etat_worker", à côté de la collection des jobs."""
    worker.publier_gpus_si_necessaire(jobs)

    assert etat_gpus.lire_etat_gpus(etat)["gpus"] == GPUS


def test_le_worker_ne_publie_pas_plus_d_une_fois_par_intervalle(jobs, releves):
    """Appelée à chaque tour de boucle, la publication n'interroge nvidia-smi qu'à intervalle régulier."""
    worker.publier_gpus_si_necessaire(jobs)
    worker.publier_gpus_si_necessaire(jobs)
    worker.publier_gpus_si_necessaire(jobs)

    assert len(releves) == 1


def test_forcer_publie_tout_de_suite(jobs, releves):
    """Au démarrage, le worker force le premier relevé."""
    worker.publier_gpus_si_necessaire(jobs)
    worker.publier_gpus_si_necessaire(jobs, forcer=True)

    assert len(releves) == 2


def test_le_worker_publie_a_nouveau_apres_l_intervalle(jobs, releves, monkeypatch):
    """Une fois l'intervalle écoulé, un nouveau relevé est publié."""
    worker.publier_gpus_si_necessaire(jobs)
    # On fait comme si le dernier relevé datait d'il y a longtemps
    monkeypatch.setattr(worker, "_derniere_publication", worker.time.monotonic() - 60)

    worker.publier_gpus_si_necessaire(jobs)

    assert len(releves) == 2


def test_une_panne_de_mongodb_n_interrompt_pas_le_worker(releves, capsys):
    """Si MongoDB ne répond pas, la publication échoue en silence (un message est affiché)."""
    class CollectionEnPanne:
        @property
        def database(self):
            raise PyMongoError("MongoDB injoignable")

    worker.publier_gpus_si_necessaire(CollectionEnPanne())

    assert "non publié" in capsys.readouterr().out


def test_le_worker_publie_pendant_la_surveillance_d_un_job(jobs, etat, releves, monkeypatch, tmp_path):
    """Pendant un long entraînement, l'état des GPU reste à jour."""
    monkeypatch.setattr(worker, "INTERVALLE_SURVEILLANCE", 0.05)
    job_id = file_jobs.creer_job(jobs, file_jobs.TYPE_PATCHING, {})
    # Un script qui dure un peu, pour que la surveillance fasse quelques tours
    processus = worker.lancer_processus(
        [sys.executable, "-c", "import time; time.sleep(0.3)"], tmp_path / "faux.log"
    )

    worker.surveiller(jobs, job_id, processus)

    assert etat_gpus.lire_etat_gpus(etat)["gpus"] == GPUS


def test_patching_worker_actif_sans_publication(etat, monkeypatch):
    """Sans signal de vie du worker, la page du patching le considère absent."""
    monkeypatch.setattr(etat_gpus, "get_etat_worker_collection", lambda: etat)

    assert etape_patching.worker_actif() is False


def test_patching_worker_actif_apres_publication(etat, monkeypatch):
    """Dès que le worker publie son état, la page du patching le voit actif."""
    monkeypatch.setattr(etat_gpus, "get_etat_worker_collection", lambda: etat)
    etat_gpus.publier_etat_gpus(etat, GPUS)

    assert etape_patching.worker_actif() is True
