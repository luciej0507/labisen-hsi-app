"""
tests/jobs/test_worker.py : tests de worker.py.

Aucun vrai patching ni entraînement n'est lancé : on remplace le script par
une toute petite commande Python (qui réussit, échoue ou dort), pour vérifier
que le worker note correctement l'état de chaque job.
Aucune connexion réelle à MongoDB : on utilise la fausse collection "jobs".
"""

import os
import sys
from types import SimpleNamespace

import pytest
from pymongo.errors import PyMongoError

import worker
from modules import jobs as file_jobs


@pytest.fixture(autouse=True)
def environnement_de_test(monkeypatch, tmp_path):
    """
    Prépare un décor sûr pour chaque test :
    - on travaille dans un dossier temporaire (les chemins relatifs du
      worker, comme suivi_patching/, n'écrivent donc rien dans le projet) ;
    - la surveillance est rapide, pour que les tests ne soient pas lents.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(worker, "INTERVALLE_SURVEILLANCE", 0.05)
    monkeypatch.setattr(worker, "DELAI_ARRET_POLI", 2)
    # Pas de vrai nvidia-smi dans les tests
    monkeypatch.setattr(worker, "interroger_gpus", lambda: [])


def faux_lancement(code_python: str, tmp_path):
    """
    Fabrique une fausse fonction de lancement : au lieu du vrai script, elle
    lance "python -c <code_python>". Renvoie ce que renvoie lancer_patching_job.
    """
    def _lancer(job):
        journal = tmp_path / "faux.log"
        processus = worker.lancer_processus([sys.executable, "-c", code_python], journal)
        return processus, {"journal": str(journal)}

    return _lancer


def job_patching(jobs, **options):
    """Crée un job de patching avec des paramètres plausibles."""
    parametres = {
        "chemin_dataset": "/data/avoine",
        "splits": ["Train", "Val"],
        "noms_formats": ["w100_h100_sl50_sc50"],
        "full_width": False,
    }
    return file_jobs.creer_job(jobs, file_jobs.TYPE_PATCHING, parametres, **options)


# ---------------------------------------------------------------------------
# File d'attente
# ---------------------------------------------------------------------------

def test_traiter_un_job_sur_une_file_vide_renvoie_false(jobs):
    """Sans job en attente, le worker n'a rien à faire."""
    assert worker.traiter_un_job(jobs) is False


# ---------------------------------------------------------------------------
# Résultat d'un job
# ---------------------------------------------------------------------------

def test_un_script_qui_reussit_donne_un_job_termine(jobs, monkeypatch, tmp_path):
    """Code de sortie 0 : le job est "termine", avec son pid et son journal."""
    monkeypatch.setattr(worker, "lancer_patching_job", faux_lancement("pass", tmp_path))
    job_id = job_patching(jobs)

    assert worker.traiter_un_job(jobs) is True

    job = file_jobs.lire_job(jobs, job_id)
    assert job["etat"] == file_jobs.TERMINE
    assert job["pid"] is not None
    assert job["journal"].endswith("faux.log")
    assert job["termine_le"] is not None


def test_un_script_qui_echoue_donne_un_job_en_erreur(jobs, monkeypatch, tmp_path):
    """Code de sortie différent de 0 : le job est "erreur", avec le code dans le message."""
    monkeypatch.setattr(
        worker, "lancer_patching_job", faux_lancement("import sys; sys.exit(3)", tmp_path)
    )
    job_id = job_patching(jobs)

    worker.traiter_un_job(jobs)

    job = file_jobs.lire_job(jobs, job_id)
    assert job["etat"] == file_jobs.ERREUR
    assert "code 3" in job["message"]


def test_un_lancement_impossible_donne_un_job_en_erreur(jobs, monkeypatch):
    """Si le lancement lui-même échoue, le job passe en erreur au lieu de bloquer le worker."""
    def lancement_en_panne(job):
        raise FileNotFoundError("CSV introuvable")

    monkeypatch.setattr(worker, "lancer_patching_job", lancement_en_panne)
    job_id = job_patching(jobs)

    worker.traiter_un_job(jobs)

    job = file_jobs.lire_job(jobs, job_id)
    assert job["etat"] == file_jobs.ERREUR
    assert "CSV introuvable" in job["message"]


def test_un_type_de_job_inconnu_donne_un_job_en_erreur(jobs):
    """Un job de type inconnu (inséré à la main) est mis en erreur."""
    resultat = jobs.insert_one({
        "type": "cuisine",
        "etat": file_jobs.EN_ATTENTE,
        "parametres": {},
        "gpu": None,
        "cree_le": file_jobs.maintenant(),
    })

    worker.traiter_un_job(jobs)

    job = file_jobs.lire_job(jobs, resultat.inserted_id)
    assert job["etat"] == file_jobs.ERREUR
    assert "inconnu" in job["message"]


def test_le_worker_enchaine_les_jobs_dans_l_ordre(jobs, monkeypatch, tmp_path):
    """Deux jobs en attente sont traités l'un après l'autre."""
    monkeypatch.setattr(worker, "lancer_patching_job", faux_lancement("pass", tmp_path))
    premier = job_patching(jobs)
    deuxieme = job_patching(jobs)

    assert worker.traiter_un_job(jobs) is True
    assert file_jobs.lire_job(jobs, premier)["etat"] == file_jobs.TERMINE
    assert file_jobs.lire_job(jobs, deuxieme)["etat"] == file_jobs.EN_ATTENTE

    assert worker.traiter_un_job(jobs) is True
    assert file_jobs.lire_job(jobs, deuxieme)["etat"] == file_jobs.TERMINE

    assert worker.traiter_un_job(jobs) is False


def test_une_panne_de_mongodb_pendant_la_surveillance_ne_tue_pas_le_script(jobs, monkeypatch, tmp_path):
    """
    Si MongoDB ne répond pas un instant, le script continue de tourner et le
    job se termine normalement : la surveillance réessaie au tour suivant.
    """
    appels = []

    def mettre_a_jour_en_panne(*arguments, **options):
        appels.append(1)
        raise PyMongoError("MongoDB injoignable")

    monkeypatch.setattr(worker, "mettre_a_jour", mettre_a_jour_en_panne)
    job_id = job_patching(jobs)
    processus = worker.lancer_processus(
        [sys.executable, "-c", "import time; time.sleep(0.3)"], tmp_path / "faux.log"
    )

    resultat, code = worker.surveiller(jobs, job_id, processus)

    assert resultat == file_jobs.TERMINE
    assert code == 0
    assert len(appels) >= 2  # la surveillance a bien réessayé


# ---------------------------------------------------------------------------
# Arrêt demandé
# ---------------------------------------------------------------------------

def test_un_arret_demande_arrete_vraiment_le_script(jobs, monkeypatch, tmp_path):
    """
    Le script dort 60 secondes. Avec l'arrêt demandé, le worker le tue vite,
    note "annule", et le processus n'existe plus.
    """
    monkeypatch.setattr(
        worker, "lancer_patching_job",
        faux_lancement("import time; time.sleep(60)", tmp_path),
    )
    job_id = job_patching(jobs)
    # On pose la demande d'arrêt directement, comme le ferait l'application
    # sur un job "en cours" (voir demander_arret)
    file_jobs.mettre_a_jour(jobs, job_id, arret_demande=True)

    worker.traiter_un_job(jobs)

    job = file_jobs.lire_job(jobs, job_id)
    assert job["etat"] == file_jobs.ANNULE
    with pytest.raises(ProcessLookupError):
        os.kill(job["pid"], 0)  # le signal 0 vérifie seulement si le processus existe


def test_un_arret_note_annule_dans_le_suivi_du_patching(jobs, monkeypatch, tmp_path):
    """Après un arrêt, le fichier de suivi lu par l'interface indique "annule"."""
    def lancement_avec_suivi(job):
        # Comme le vrai lancement : un suivi "en cours" est écrit
        worker.ecrire_suivi_local("/data/avoine", {"etat": "en cours", "cubes_faits": 4})
        return faux_lancement("import time; time.sleep(60)", tmp_path)(job)

    monkeypatch.setattr(worker, "lancer_patching_job", lancement_avec_suivi)
    job_id = job_patching(jobs)
    file_jobs.mettre_a_jour(jobs, job_id, arret_demande=True)

    worker.traiter_un_job(jobs)

    suivi = worker.lire_suivi("/data/avoine")
    assert suivi["etat"] == "annule"
    assert suivi["cubes_faits"] == 4  # le reste du suivi est conservé


def test_l_arret_du_worker_marque_le_job_interrompu(jobs, monkeypatch, tmp_path):
    """Si le worker reçoit Ctrl+C pendant un job, le script est arrêté et le job est "interrompu"."""
    monkeypatch.setattr(
        worker, "lancer_patching_job",
        faux_lancement("import time; time.sleep(60)", tmp_path),
    )

    def ctrl_c(*arguments):
        raise KeyboardInterrupt

    # On simule Ctrl+C au premier passage dans la boucle de surveillance
    monkeypatch.setattr(worker, "arret_est_demande", ctrl_c)
    job_id = job_patching(jobs)

    with pytest.raises(KeyboardInterrupt):
        worker.traiter_un_job(jobs)

    job = file_jobs.lire_job(jobs, job_id)
    assert job["etat"] == file_jobs.INTERROMPU
    with pytest.raises(ProcessLookupError):
        os.kill(job["pid"], 0)


# ---------------------------------------------------------------------------
# Construction des commandes
# ---------------------------------------------------------------------------

def test_lancer_patching_job_construit_la_bonne_commande(jobs, monkeypatch):
    """La commande contient le dataset, les splits en minuscules, les formats et le suivi."""
    commandes = []

    def faux_lancer_processus(commande, fichier_journal, environnement=None):
        commandes.append(commande)
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr(worker, "lancer_processus", faux_lancer_processus)
    parametres = {
        "chemin_dataset": "/data/avoine",
        "splits": ["Train", "Val"],
        "noms_formats": ["w100_h100_sl50_sc50", "w200_h200_sl100_sc100"],
        "full_width": True,
    }
    job_id = file_jobs.creer_job(jobs, file_jobs.TYPE_PATCHING, parametres)

    processus, infos = worker.lancer_patching_job(file_jobs.lire_job(jobs, job_id))

    commande = commandes[0]
    assert commande[commande.index("--dataset") + 1] == "/data/avoine"
    assert "train" in commande and "val" in commande
    assert "Train" not in commande
    assert "w100_h100_sl50_sc50" in commande and "w200_h200_sl100_sc100" in commande
    assert "--full-width" in commande
    assert "--suivi" in commande
    assert processus.pid == 4242
    assert infos["journal"].endswith(".log")


def test_lancer_patching_job_efface_le_suivi_d_un_ancien_patching(jobs, monkeypatch):
    """
    Le suivi d'un ancien patching est supprimé avant le lancement : l'interface
    ne doit pas le prendre pour l'avancement du nouveau job.
    """
    worker.ecrire_suivi_local("/data/avoine", {"etat": "termine", "cubes_faits": 99})
    vus_au_lancement = []

    def faux_lancer_processus(commande, fichier_journal, environnement=None):
        # À cet instant, l'ancien suivi ne doit plus exister
        vus_au_lancement.append(worker.lire_suivi("/data/avoine"))
        return SimpleNamespace(pid=4242)

    monkeypatch.setattr(worker, "lancer_processus", faux_lancer_processus)
    job_id = job_patching(jobs)

    worker.lancer_patching_job(file_jobs.lire_job(jobs, job_id))

    assert vus_au_lancement == [None]


def test_lancer_patching_job_ecrit_un_premier_suivi_avec_le_pid(jobs, monkeypatch):
    """Un suivi "en cours" est écrit tout de suite, avec le pid du script."""
    monkeypatch.setattr(
        worker, "lancer_processus", lambda *arguments, **options: SimpleNamespace(pid=4242)
    )
    job_id = job_patching(jobs)

    worker.lancer_patching_job(file_jobs.lire_job(jobs, job_id))

    suivi = worker.lire_suivi("/data/avoine")
    assert suivi["etat"] == "en cours"
    assert suivi["pid"] == 4242
    assert suivi["splits"] == ["Train", "Val"]


def preparer_dataset_entrainement(tmp_path):
    """Crée un faux dataset avec le CSV d'entraînement que le worker doit trouver."""
    dataset = tmp_path / "dataset"
    dossier_csv = (
        dataset / "hsi_data_patching" / "HSI" / "csv_for_dataloader" / "train" / "w100"
    )
    dossier_csv.mkdir(parents=True)
    (dossier_csv / "100%_train_w100.csv").write_text("chemin\n")
    return dataset


def config_entrainement():
    """Configuration minimale, avec la forme attendue par lancer_entrainement_job."""
    return {
        "format_patches": "w100",
        "fraction_csv": 100,
        "split": "train",
        "parametres_generaux": {"validation": False, "epochs": 2},
    }


def test_lancer_entrainement_job_prepare_le_run(jobs, monkeypatch, tmp_path):
    """Le run reçoit son config.json, son status.json, et le script ne voit que le GPU choisi."""
    appels = []

    def faux_lancer_processus(commande, fichier_journal, environnement=None):
        appels.append({"commande": commande, "environnement": environnement})
        return SimpleNamespace(pid=999)

    monkeypatch.setattr(worker, "lancer_processus", faux_lancer_processus)
    monkeypatch.setattr(worker, "demarrer_mlflow", lambda: None)
    monkeypatch.setattr(worker, "DOSSIER_RUNS", tmp_path / "runs")
    (tmp_path / "runs").mkdir()

    dataset = preparer_dataset_entrainement(tmp_path)
    job_id = file_jobs.creer_job(
        jobs, file_jobs.TYPE_ENTRAINEMENT,
        {"dataset": str(dataset), "config": config_entrainement()},
        gpu=2,
    )

    processus, infos = worker.lancer_entrainement_job(file_jobs.lire_job(jobs, job_id))

    # Le script est lancé avec le dossier du run et le bon GPU, numéroté comme
    # dans nvidia-smi
    assert appels[0]["environnement"]["CUDA_VISIBLE_DEVICES"] == "2"
    assert appels[0]["environnement"]["CUDA_DEVICE_ORDER"] == "PCI_BUS_ID"
    assert "--dossier" in appels[0]["commande"]
    assert infos["dossier"] in appels[0]["commande"]

    # Les fichiers lus par le script sont écrits
    dossier = tmp_path / "runs" / os.path.basename(infos["dossier"])
    config = worker.lire_json(dossier / "config.json")
    assert config["gpu"] == 2
    assert config["csv"]["train"].endswith("100%_train_w100.csv")
    assert "val" not in config["csv"]
    assert config["parametres_generaux"]["epochs"] == 2
    assert worker.lire_json(dossier / "status.json") == {"state": "starting"}
    assert infos["journal"].endswith("train.log")


def test_lancer_entrainement_job_sans_gpu_est_refuse(jobs):
    """Sans GPU choisi, le lancement est refusé avec un message clair."""
    job_id = file_jobs.creer_job(
        jobs, file_jobs.TYPE_ENTRAINEMENT,
        {"dataset": "/data/avoine", "config": config_entrainement()},
    )

    with pytest.raises(ValueError, match="GPU"):
        worker.lancer_entrainement_job(file_jobs.lire_job(jobs, job_id))


def test_lancer_entrainement_job_csv_manquant_donne_un_job_en_erreur(jobs, monkeypatch, tmp_path):
    """Si le CSV du split est introuvable, le job passe en erreur proprement."""
    monkeypatch.setattr(worker, "demarrer_mlflow", lambda: None)
    job_id = file_jobs.creer_job(
        jobs, file_jobs.TYPE_ENTRAINEMENT,
        {"dataset": str(tmp_path / "inexistant"), "config": config_entrainement()},
        gpu=0,
    )

    worker.traiter_un_job(jobs)

    job = file_jobs.lire_job(jobs, job_id)
    assert job["etat"] == file_jobs.ERREUR
    assert "CSV introuvable" in job["message"]


def test_noter_arret_entrainement_met_status_a_stopped(tmp_path):
    """Après un arrêt, status.json indique "stopped" et garde le reste."""
    dossier = tmp_path / "run"
    dossier.mkdir()
    worker.ecrire_json(dossier / "status.json", {"state": "running", "epoch": 3})

    worker.noter_arret_entrainement({"dossier": str(dossier)})

    statut = worker.lire_json(dossier / "status.json")
    assert statut["state"] == "stopped"
    assert statut["epoch"] == 3


def test_noter_arret_entrainement_sans_dossier_ne_fait_rien():
    """Un job sans dossier de run (lancement raté) ne provoque pas d'erreur."""
    worker.noter_arret_entrainement({})