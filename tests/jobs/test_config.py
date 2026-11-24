"""
tests/jobs/test_config.py : tests de modules/config.py et de son usage.

Le module config lit ses valeurs au moment de l'import. Pour tester
plusieurs valeurs de .env sans toucher au vrai module, on le charge à
chaque fois sous un autre nom (voir charger_config).
"""

import importlib.util
import subprocess
from pathlib import Path

import pytest

from modules import config
from modules.apprentissage import etape_lancement_suivi, gestion_entrainement

# Variables lues par modules/config.py
VARIABLES = (
    "DOSSIER_DONNEES_APP",
    "MLFLOW_URL_INTERNE",
    "MLFLOW_URL_PUBLIQUE",
    "MLFLOW_DEMARRAGE_AUTO",
)


@pytest.fixture
def charger_config(monkeypatch):
    """
    Fournit une fonction qui charge une copie neuve de modules/config.py.

    Le vrai fichier .env est ignoré (load_dotenv ne fait rien) et les
    variables du test sont retirées de l'environnement avant chaque
    chargement : seules celles passées en paramètre existent.
    """
    monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: None)

    def _charger(**valeurs):
        for nom in VARIABLES:
            monkeypatch.delenv(nom, raising=False)
        for nom, valeur in valeurs.items():
            monkeypatch.setenv(nom, valeur)
        spec = importlib.util.spec_from_file_location("config_de_test", config.__file__)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _charger


# ------------------------------------------------------------ valeurs par défaut


def test_valeurs_par_defaut(charger_config):
    cfg = charger_config()
    assert cfg.MLFLOW_URL_INTERNE == "http://127.0.0.1:5000"
    assert cfg.MLFLOW_URL_PUBLIQUE == "http://127.0.0.1:5000"
    assert cfg.MLFLOW_DEMARRAGE_AUTO is True
    # Sans DOSSIER_DONNEES_APP, on travaille dans la racine du projet
    assert cfg.DOSSIER_DONNEES_APP == cfg.RACINE_PROJET


def test_racine_du_projet_contient_worker_py():
    assert (config.RACINE_PROJET / "worker.py").is_file()


# ------------------------------------------------------ valeurs du fichier .env


def test_adresse_publique_differente_de_l_adresse_interne(charger_config):
    cfg = charger_config(
        MLFLOW_URL_INTERNE="http://mlflow:5000",
        MLFLOW_URL_PUBLIQUE="http://serveur-ecole:5000",
    )
    assert cfg.MLFLOW_URL_INTERNE == "http://mlflow:5000"
    assert cfg.MLFLOW_URL_PUBLIQUE == "http://serveur-ecole:5000"


def test_adresse_publique_par_defaut_egale_a_l_adresse_interne(charger_config):
    cfg = charger_config(MLFLOW_URL_INTERNE="http://mlflow:5000")
    assert cfg.MLFLOW_URL_PUBLIQUE == "http://mlflow:5000"


def test_le_slash_final_des_adresses_est_retire(charger_config):
    cfg = charger_config(
        MLFLOW_URL_INTERNE="http://mlflow:5000/",
        MLFLOW_URL_PUBLIQUE="http://serveur-ecole:5000/",
    )
    assert cfg.MLFLOW_URL_INTERNE == "http://mlflow:5000"
    assert cfg.MLFLOW_URL_PUBLIQUE == "http://serveur-ecole:5000"


@pytest.mark.parametrize("valeur, attendu", [("1", True), ("0", False), ("non", False)])
def test_demarrage_automatique_de_mlflow(charger_config, valeur, attendu):
    cfg = charger_config(MLFLOW_DEMARRAGE_AUTO=valeur)
    assert cfg.MLFLOW_DEMARRAGE_AUTO is attendu


def test_dossier_de_donnees_configurable(charger_config, tmp_path):
    cfg = charger_config(DOSSIER_DONNEES_APP=str(tmp_path))
    assert cfg.DOSSIER_DONNEES_APP == Path(tmp_path)


def test_dossier_de_donnees_vide_donne_la_racine_du_projet(charger_config):
    cfg = charger_config(DOSSIER_DONNEES_APP="")
    assert cfg.DOSSIER_DONNEES_APP == cfg.RACINE_PROJET


# ---------------------------------------------------------- usage dans l'appli


def test_le_lien_mlflow_utilise_l_adresse_publique(monkeypatch):
    monkeypatch.setattr(etape_lancement_suivi, "MLFLOW_URL_PUBLIQUE", "http://serveur-ecole:5000")
    statut = {"run_id": "abc", "experiment_id": "7"}
    assert etape_lancement_suivi.url_mlflow(statut) == (
        "http://serveur-ecole:5000/#/experiments/7/runs/abc"
    )


def test_le_lien_mlflow_sans_run_pointe_vers_l_accueil(monkeypatch):
    monkeypatch.setattr(etape_lancement_suivi, "MLFLOW_URL_PUBLIQUE", "http://serveur-ecole:5000")
    assert etape_lancement_suivi.url_mlflow({}) == "http://serveur-ecole:5000"


def test_demarrer_mlflow_ne_fait_rien_si_le_demarrage_auto_est_desactive(monkeypatch):
    monkeypatch.setattr(gestion_entrainement, "MLFLOW_DEMARRAGE_AUTO", False)
    # MLflow ne répond pas : s'il était démarré, Popen serait appelé
    monkeypatch.setattr(gestion_entrainement, "mlflow_actif", lambda: False)

    def popen_interdit(*args, **kwargs):
        raise AssertionError("MLflow ne doit pas être démarré")

    monkeypatch.setattr(subprocess, "Popen", popen_interdit)

    gestion_entrainement.demarrer_mlflow()  # ne doit lever aucune erreur


def test_les_dossiers_de_travail_sont_sous_le_dossier_de_donnees():
    assert gestion_entrainement.DOSSIER_ENTRAINEMENTS == config.DOSSIER_DONNEES_APP / "entrainements"
    assert gestion_entrainement.DOSSIER_RUNS == gestion_entrainement.DOSSIER_ENTRAINEMENTS / "runs"
