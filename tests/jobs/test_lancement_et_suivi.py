"""
tests/jobs/test_lancement_et_suivi.py : tests des fonctions de l'application
qui passent par la file d'attente (modules/apprentissage/etape_patching.py et
modules/apprentissage/gestion_entrainement.py).

Aucune connexion réelle à MongoDB : on remplace la collection par la fausse
collection "jobs" (mongomock). Aucun script n'est lancé : ici, on joue le rôle
du worker en changeant l'état des jobs à la main.
"""

import sys

import pytest

import worker
from modules import jobs as file_jobs
from modules.apprentissage import etape_patching, gestion_entrainement
from modules.apprentissage.etape_lancement_suivi import etat_du_run

DATASET = "/data/avoine"


@pytest.fixture(autouse=True)
def decor(monkeypatch, tmp_path, jobs):
    """
    Prépare un décor sûr pour chaque test :
    - on travaille dans un dossier temporaire (les fichiers de suivi du
      patching, qui ont un chemin relatif, n'écrivent rien dans le projet) ;
    - les deux modules utilisent la fausse collection au lieu de MongoDB.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(etape_patching, "get_jobs_collection", lambda: jobs)
    monkeypatch.setattr(gestion_entrainement, "get_jobs_collection", lambda: jobs)


def demarrer(jobs):
    """Fait comme le worker : réserve le prochain job (il passe "en cours")."""
    return file_jobs.reserver_prochain_job(jobs)


def lancer_un_patching(dataset=DATASET, **options):
    """Lance un patching avec des paramètres plausibles."""
    return etape_patching.lancer_patching(
        dataset, ["Train", "Val"], ["w100_h100_sl50_sc50"], False, **options
    )


# ---------------------------------------------------------------------------
# Patching : lancement
# ---------------------------------------------------------------------------

def test_lancer_patching_depose_un_job_en_attente(jobs):
    """Lancer un patching crée un job "en attente" et ne lance aucun calcul."""
    job_id = lancer_un_patching(utilisateur="alice")

    job = file_jobs.lire_job(jobs, job_id)
    assert job["type"] == file_jobs.TYPE_PATCHING
    assert job["etat"] == file_jobs.EN_ATTENTE
    assert job["cle"] == DATASET
    assert job["utilisateur"] == "alice"
    assert job["parametres"] == {
        "chemin_dataset": DATASET,
        "splits": ["Train", "Val"],
        "noms_formats": ["w100_h100_sl50_sc50"],
        "full_width": False,
    }


def test_lancer_patching_refuse_un_deuxieme_patching_sur_le_meme_dataset(jobs):
    """Un patching est déjà en attente ou en cours : le second est refusé."""
    lancer_un_patching()

    with pytest.raises(RuntimeError, match="déjà"):
        lancer_un_patching()

    assert jobs.count_documents({}) == 1


def test_lancer_patching_accepte_un_autre_dataset(jobs):
    """Les datasets sont indépendants."""
    lancer_un_patching("/data/avoine")
    lancer_un_patching("/data/ble")

    assert jobs.count_documents({}) == 2


def test_lancer_patching_est_possible_apres_la_fin_du_precedent(jobs):
    """Une fois le premier patching fini, on peut en relancer un."""
    premier = lancer_un_patching()
    file_jobs.terminer_job(jobs, premier, file_jobs.TERMINE)

    lancer_un_patching()

    assert jobs.count_documents({}) == 2


def test_le_chemin_du_dataset_peut_etre_un_texte_ou_un_chemin(jobs):
    """Le dataset est retrouvé qu'il soit donné en texte ou en Path."""
    from pathlib import Path

    lancer_un_patching(Path(DATASET))

    assert etape_patching.etat_job(DATASET) is not None
    assert etape_patching.etat_job(Path(DATASET)) is not None


# ---------------------------------------------------------------------------
# Patching : état
# ---------------------------------------------------------------------------

def test_etat_job_sans_job_ni_fichier_renvoie_none():
    """Un dataset jamais patché n'a pas d'état."""
    assert etape_patching.etat_job(DATASET) is None


def test_etat_job_en_attente_se_presente_comme_une_preparation(jobs):
    """
    Pour l'interface, un job en attente est un patching "en cours" à 0 cube,
    avec le drapeau en_attente pour le distinguer.
    """
    lancer_un_patching()

    suivi = etape_patching.etat_job(DATASET)

    assert suivi["etat"] == "en cours"
    assert suivi["en_attente"] is True
    assert suivi["cubes_faits"] == 0
    assert suivi["cubes_total"] == 0
    assert suivi["format"] == ""
    assert suivi["splits"] == ["Train", "Val"]


def test_etat_job_en_attente_ignore_le_suivi_d_un_ancien_patching(jobs):
    """Le fichier de suivi d'un ancien patching n'est pas affiché pour le nouveau job."""
    etape_patching.ecrire_suivi_local(DATASET, {"etat": "termine", "cubes_faits": 9, "cubes_total": 9})
    lancer_un_patching()

    suivi = etape_patching.etat_job(DATASET)

    assert suivi["etat"] == "en cours"
    assert suivi["cubes_faits"] == 0


def test_etat_job_en_cours_lit_l_avancement_dans_le_fichier_du_script(jobs):
    """L'état vient de MongoDB, le détail de l'avancement du fichier de suivi."""
    lancer_un_patching()
    demarrer(jobs)
    etape_patching.ecrire_suivi_local(DATASET, {
        "etat": "en cours",
        "format": "w100_h100_sl50_sc50",
        "splits": ["Train"],
        "cubes_total": 10,
        "cubes_faits": 4,
        "cube_courant": "cube_05 (train)",
        "message": "",
    })

    suivi = etape_patching.etat_job(DATASET)

    assert suivi["etat"] == "en cours"
    assert suivi["en_attente"] is False
    assert suivi["format"] == "w100_h100_sl50_sc50"
    assert suivi["cubes_total"] == 10
    assert suivi["cubes_faits"] == 4
    assert suivi["cube_courant"] == "cube_05 (train)"


def test_etat_job_ne_depend_pas_du_numero_de_processus(jobs):
    """
    Le numéro de processus écrit dans le suivi n'est plus vérifié : il
    appartient au worker, qui peut être dans un autre container.
    Un numéro qui n'existe pas ici ne rend pas le patching "interrompu".
    """
    lancer_un_patching()
    demarrer(jobs)
    etape_patching.ecrire_suivi_local(DATASET, {"etat": "en cours", "pid": 999999})

    assert etape_patching.etat_job(DATASET)["etat"] == "en cours"


def test_etat_job_termine_garde_le_message_du_script(jobs):
    """Le message précis du script est affiché à la fin du patching."""
    job_id = lancer_un_patching()
    demarrer(jobs)
    etape_patching.ecrire_suivi_local(DATASET, {"etat": "termine", "message": "12 cube(s) traité(s)"})
    file_jobs.terminer_job(jobs, job_id, file_jobs.TERMINE, "Traitement terminé.")

    suivi = etape_patching.etat_job(DATASET)

    assert suivi["etat"] == "termine"
    assert suivi["message"] == "12 cube(s) traité(s)"


def test_etat_job_erreur_sans_message_du_script_utilise_celui_du_worker(jobs):
    """Si le script n'a rien écrit, on affiche le message du worker."""
    job_id = lancer_un_patching()
    demarrer(jobs)
    file_jobs.terminer_job(jobs, job_id, file_jobs.ERREUR, "Le script s'est arrêté (code 1).")

    suivi = etape_patching.etat_job(DATASET)

    assert suivi["etat"] == "erreur"
    assert "code 1" in suivi["message"]


def test_etat_job_interrompu(jobs):
    """Un job interrompu (worker arrêté) est signalé, même si le fichier dit "en cours"."""
    job_id = lancer_un_patching()
    demarrer(jobs)
    etape_patching.ecrire_suivi_local(DATASET, {"etat": "en cours"})
    file_jobs.marquer_interrompus(jobs)

    suivi = etape_patching.etat_job(DATASET)

    assert file_jobs.lire_job(jobs, job_id)["etat"] == file_jobs.INTERROMPU
    assert suivi["etat"] == "interrompu"
    assert "worker" in suivi["message"]


def test_etat_job_sans_job_reprend_l_ancien_suivi_termine():
    """Le résultat d'un patching lancé avant la file d'attente reste affiché."""
    etape_patching.ecrire_suivi_local(DATASET, {"etat": "termine", "message": "3 cube(s)"})

    suivi = etape_patching.etat_job(DATASET)

    assert suivi["etat"] == "termine"
    assert suivi["en_attente"] is False


def test_etat_job_sans_job_ancien_suivi_en_cours_devient_interrompu():
    """Plus personne ne s'occupe d'un ancien patching noté "en cours"."""
    etape_patching.ecrire_suivi_local(DATASET, {"etat": "en cours"})

    assert etape_patching.etat_job(DATASET)["etat"] == "interrompu"


# ---------------------------------------------------------------------------
# Patching : annulation et masquage
# ---------------------------------------------------------------------------

def test_annuler_un_patching_en_attente_l_annule_tout_de_suite(jobs):
    """Un patching qui n'a pas démarré est annulé immédiatement."""
    lancer_un_patching()

    etape_patching.annuler_patching(DATASET)

    assert etape_patching.etat_job(DATASET)["etat"] == "annule"


def test_annuler_un_patching_en_cours_demande_l_arret_au_worker(jobs):
    """Pour un patching en cours, l'application pose la demande et le worker agit."""
    job_id = lancer_un_patching()
    demarrer(jobs)

    etape_patching.annuler_patching(DATASET)

    assert file_jobs.arret_est_demande(jobs, job_id) is True
    suivi = etape_patching.etat_job(DATASET)
    assert suivi["etat"] == "en cours"  # le worker n'a pas encore arrêté le script
    assert suivi["arret_demande"] is True


def test_annuler_sans_job_ne_fait_rien():
    """Annuler un dataset sans patching ne provoque pas d'erreur."""
    etape_patching.annuler_patching(DATASET)


def test_effacer_suivi_masque_le_resultat_et_supprime_le_fichier(jobs):
    """Après "Masquer ce message", plus rien n'est affiché pour ce dataset."""
    job_id = lancer_un_patching()
    demarrer(jobs)
    etape_patching.ecrire_suivi_local(DATASET, {"etat": "termine"})
    file_jobs.terminer_job(jobs, job_id, file_jobs.TERMINE)

    etape_patching.effacer_suivi(DATASET)

    assert etape_patching.etat_job(DATASET) is None
    assert etape_patching.lire_suivi(DATASET) is None


def test_effacer_suivi_ne_touche_pas_a_un_patching_en_cours(jobs):
    """Un patching qui tourne n'est ni masqué ni privé de son suivi."""
    lancer_un_patching()
    demarrer(jobs)
    etape_patching.ecrire_suivi_local(DATASET, {"etat": "en cours", "cubes_faits": 2})

    etape_patching.effacer_suivi(DATASET)

    assert etape_patching.etat_job(DATASET)["cubes_faits"] == 2


def test_masquer_ne_fait_pas_reapparaitre_un_ancien_resultat(jobs):
    """Après masquage du dernier patching, le résultat du précédent ne revient pas."""
    premier = lancer_un_patching()
    file_jobs.reserver_prochain_job(jobs)
    file_jobs.terminer_job(jobs, premier, file_jobs.TERMINE)
    deuxieme = lancer_un_patching()
    file_jobs.reserver_prochain_job(jobs)
    file_jobs.terminer_job(jobs, deuxieme, file_jobs.ERREUR, "échec")

    etape_patching.effacer_suivi(DATASET)

    assert etape_patching.etat_job(DATASET) is None


# ---------------------------------------------------------------------------
# Entraînement : lancement
# ---------------------------------------------------------------------------

def config_entrainement(validation=False):
    """Configuration minimale, avec la forme attendue par lancer_entrainement."""
    return {
        "format_patches": "w100",
        "fraction_csv": 100,
        "split": "train",
        "parametres_generaux": {"validation": validation, "epochs": 2},
        # Un tuple : il doit être enregistré comme une liste
        "hyperparametres": {"couches": (1, 2, 3)},
    }


def preparer_dataset(tmp_path, avec_val=False):
    """Crée un faux dataset avec les CSV que lancer_entrainement vérifie."""
    dataset = tmp_path / "dataset"
    racine = dataset / "hsi_data_patching" / "HSI" / "csv_for_dataloader"
    splits = ["train", "val"] if avec_val else ["train"]
    for split in splits:
        dossier = racine / split / "w100"
        # exist_ok : un test peut appeler cette fonction plusieurs fois
        dossier.mkdir(parents=True, exist_ok=True)
        (dossier / f"100%_{split}_w100.csv").write_text("chemin\n")
    return dataset


def lancer_un_entrainement(tmp_path, **options):
    """Lance un entraînement sur un faux dataset complet."""
    dataset = preparer_dataset(tmp_path, avec_val=True)
    return gestion_entrainement.lancer_entrainement(
        dataset, config_entrainement(), gpu=1, **options
    )


def test_lancer_entrainement_depose_un_job_en_attente(jobs, tmp_path):
    """Lancer un entraînement crée un job "en attente" avec le GPU et la configuration."""
    job_id = lancer_un_entrainement(tmp_path, utilisateur="alice")

    job = file_jobs.lire_job(jobs, job_id)
    assert job["type"] == file_jobs.TYPE_ENTRAINEMENT
    assert job["etat"] == file_jobs.EN_ATTENTE
    assert job["gpu"] == 1
    assert job["utilisateur"] == "alice"
    assert job["parametres"]["dataset"] == str(tmp_path / "dataset")
    # Le tuple est devenu une liste
    assert job["parametres"]["config"]["hyperparametres"]["couches"] == [1, 2, 3]


def test_lancer_entrainement_refuse_un_second_entrainement(jobs, tmp_path):
    """Un seul entraînement à la fois, en attente ou en cours."""
    lancer_un_entrainement(tmp_path)

    with pytest.raises(RuntimeError, match="déjà"):
        lancer_un_entrainement(tmp_path)

    assert jobs.count_documents({}) == 1


def test_lancer_entrainement_csv_manquant_ne_cree_aucun_job(jobs, tmp_path):
    """Si le CSV est introuvable, l'erreur est immédiate et rien n'est déposé."""
    with pytest.raises(FileNotFoundError, match="CSV introuvable"):
        gestion_entrainement.lancer_entrainement(
            tmp_path / "inexistant", config_entrainement(), gpu=0
        )

    assert jobs.count_documents({}) == 0


def test_lancer_entrainement_avec_validation_exige_le_csv_val(jobs, tmp_path):
    """Avec la validation activée, le CSV du split val doit exister aussi."""
    dataset = preparer_dataset(tmp_path, avec_val=False)

    with pytest.raises(FileNotFoundError, match="val"):
        gestion_entrainement.lancer_entrainement(
            dataset, config_entrainement(validation=True), gpu=0
        )

    assert jobs.count_documents({}) == 0


# ---------------------------------------------------------------------------
# Entraînement : suivi
# ---------------------------------------------------------------------------

def test_lire_run_en_cours_sans_job_renvoie_none():
    """Sans entraînement lancé, il n'y a rien à suivre."""
    assert gestion_entrainement.lire_run_en_cours() is None


def test_run_en_attente(jobs, tmp_path):
    """Un entraînement en attente est vivant, sans dossier, et se lit comme un démarrage."""
    lancer_un_entrainement(tmp_path)

    run = gestion_entrainement.lire_run_en_cours()

    assert run["vivant"] is True
    assert run["en_attente"] is True
    assert run["dossier"] is None
    assert run["statut"] == {"state": "starting"}
    # La configuration demandée est affichée en attendant le config.json du run
    assert run["config"]["format_patches"] == "w100"
    assert etat_du_run(run) == "demarrage"
    assert gestion_entrainement.lire_log(run["dossier"]) == ""


def test_run_en_cours_lit_les_fichiers_du_run(jobs, tmp_path):
    """Une fois démarré, le statut et la configuration viennent des fichiers du run."""
    job_id = lancer_un_entrainement(tmp_path)
    demarrer(jobs)
    dossier = tmp_path / "run1"
    dossier.mkdir()
    gestion_entrainement.ecrire_json(
        dossier / "status.json", {"state": "running", "epoch": 3, "total_epochs": 10}
    )
    gestion_entrainement.ecrire_json(dossier / "config.json", {"gpu": 1, "format_patches": "w100"})
    (dossier / "train.log").write_text("ligne 1\nligne 2\n")
    file_jobs.mettre_a_jour(jobs, job_id, dossier=str(dossier), pid=123)

    run = gestion_entrainement.lire_run_en_cours()

    assert run["vivant"] is True
    assert run["en_attente"] is False
    assert run["dossier"] == dossier
    assert run["pid"] == 123
    assert run["statut"]["epoch"] == 3
    assert run["config"]["gpu"] == 1
    assert etat_du_run(run) == "en_cours"
    assert gestion_entrainement.lire_log(run["dossier"]) == "ligne 1\nligne 2"


def test_run_termine(jobs, tmp_path):
    """Un entraînement terminé n'est plus vivant."""
    job_id = lancer_un_entrainement(tmp_path)
    demarrer(jobs)
    dossier = tmp_path / "run1"
    dossier.mkdir()
    gestion_entrainement.ecrire_json(dossier / "status.json", {"state": "done"})
    file_jobs.mettre_a_jour(jobs, job_id, dossier=str(dossier))
    file_jobs.terminer_job(jobs, job_id, file_jobs.TERMINE)

    run = gestion_entrainement.lire_run_en_cours()

    assert run["vivant"] is False
    assert etat_du_run(run) == "termine"


def test_run_annule_avant_son_demarrage_se_lit_comme_arrete(jobs, tmp_path):
    """Annulé en attente : pas de status.json, mais l'interface voit un arrêt."""
    lancer_un_entrainement(tmp_path)
    gestion_entrainement.arreter_entrainement()

    run = gestion_entrainement.lire_run_en_cours()

    assert run["vivant"] is False
    assert etat_du_run(run) == "arrete"


def test_run_en_erreur_affiche_le_message_du_worker(jobs, tmp_path):
    """Sans message du script, le message du worker est celui affiché."""
    job_id = lancer_un_entrainement(tmp_path)
    demarrer(jobs)
    file_jobs.terminer_job(jobs, job_id, file_jobs.ERREUR, "Le script s'est arrêté (code 1).")

    run = gestion_entrainement.lire_run_en_cours()

    assert etat_du_run(run) == "erreur"
    assert "code 1" in run["statut"]["message"]


def test_run_interrompu_se_lit_comme_une_erreur(jobs, tmp_path):
    """Un entraînement interrompu par l'arrêt du worker est signalé en erreur, avec la cause."""
    lancer_un_entrainement(tmp_path)
    demarrer(jobs)
    file_jobs.marquer_interrompus(jobs)

    run = gestion_entrainement.lire_run_en_cours()

    assert run["vivant"] is False
    assert run["etat_job"] == file_jobs.INTERROMPU
    assert etat_du_run(run) == "erreur"
    assert "worker" in run["statut"]["message"]


def test_run_ne_depend_pas_du_numero_de_processus(jobs, tmp_path):
    """Un pid qui n'existe pas dans ce container ne rend pas l'entraînement "en erreur"."""
    job_id = lancer_un_entrainement(tmp_path)
    demarrer(jobs)
    dossier = tmp_path / "run1"
    dossier.mkdir()
    gestion_entrainement.ecrire_json(dossier / "status.json", {"state": "running"})
    file_jobs.mettre_a_jour(jobs, job_id, dossier=str(dossier), pid=999999)

    run = gestion_entrainement.lire_run_en_cours()

    assert run["vivant"] is True
    assert etat_du_run(run) == "en_cours"


# ---------------------------------------------------------------------------
# Entraînement : arrêt et masquage
# ---------------------------------------------------------------------------

def test_arreter_un_entrainement_en_cours_demande_l_arret_au_worker(jobs, tmp_path):
    """L'application pose la demande, le worker arrête le script."""
    job_id = lancer_un_entrainement(tmp_path)
    demarrer(jobs)

    gestion_entrainement.arreter_entrainement()

    assert file_jobs.arret_est_demande(jobs, job_id) is True
    run = gestion_entrainement.lire_run_en_cours()
    assert run["vivant"] is True  # pas encore arrêté par le worker
    assert run["arret_demande"] is True


def test_arreter_sans_entrainement_ne_fait_rien():
    """Arrêter quand rien ne tourne ne provoque pas d'erreur."""
    gestion_entrainement.arreter_entrainement()


def test_oublier_run_retire_un_entrainement_termine(jobs, tmp_path):
    """Après "Nouvel entraînement", le run terminé n'est plus affiché."""
    job_id = lancer_un_entrainement(tmp_path)
    demarrer(jobs)
    file_jobs.terminer_job(jobs, job_id, file_jobs.TERMINE)

    gestion_entrainement.oublier_run()

    assert gestion_entrainement.lire_run_en_cours() is None
    # Et un nouvel entraînement peut être lancé
    lancer_un_entrainement(tmp_path)


def test_oublier_run_ne_retire_pas_un_entrainement_en_cours(jobs, tmp_path):
    """Un entraînement qui tourne reste affiché."""
    lancer_un_entrainement(tmp_path)
    demarrer(jobs)

    gestion_entrainement.oublier_run()

    assert gestion_entrainement.lire_run_en_cours() is not None


# ---------------------------------------------------------------------------
# Application et worker ensemble
# ---------------------------------------------------------------------------

def faux_script(code_python, tmp_path, dossier=None):
    """
    Fabrique une fausse fonction de lancement pour le worker : elle lance
    "python -c <code_python>" à la place du vrai script.
    """
    def _lancer(job):
        journal = tmp_path / "faux.log"
        processus = worker.lancer_processus([sys.executable, "-c", code_python], journal)
        infos = {"journal": str(journal)}
        if dossier is not None:
            infos["dossier"] = str(dossier)
        return processus, infos

    return _lancer


def test_patching_de_bout_en_bout(jobs, monkeypatch, tmp_path):
    """L'application dépose le job, le worker l'exécute, l'application voit "termine"."""
    monkeypatch.setattr(worker, "lancer_patching_job", faux_script("pass", tmp_path))
    monkeypatch.setattr(worker, "INTERVALLE_SURVEILLANCE", 0.05)

    lancer_un_patching()
    assert etape_patching.etat_job(DATASET)["en_attente"] is True

    worker.traiter_un_job(jobs)

    assert etape_patching.etat_job(DATASET)["etat"] == "termine"


def test_arret_d_entrainement_de_bout_en_bout(jobs, monkeypatch, tmp_path):
    """
    L'application demande l'arrêt, le worker arrête le script et clôture le
    run : l'interface lit "arrêté".
    """
    dossier = tmp_path / "run1"
    dossier.mkdir()
    gestion_entrainement.ecrire_json(dossier / "status.json", {"state": "running"})
    monkeypatch.setattr(
        worker, "lancer_entrainement_job",
        faux_script("import time; time.sleep(60)", tmp_path, dossier),
    )
    monkeypatch.setattr(worker, "INTERVALLE_SURVEILLANCE", 0.05)
    monkeypatch.setattr(worker, "DELAI_ARRET_POLI", 2)

    job_id = lancer_un_entrainement(tmp_path)
    # Le job tourne, puis l'utilisateur clique sur "Arrêter" : la demande est
    # posée avant que le worker ne regarde (il la voit à son premier passage)
    file_jobs.mettre_a_jour(jobs, job_id, arret_demande=True)

    worker.traiter_un_job(jobs)

    run = gestion_entrainement.lire_run_en_cours()
    assert run["vivant"] is False
    assert etat_du_run(run) == "arrete"
    assert gestion_entrainement.lire_json(dossier / "status.json")["state"] == "stopped"