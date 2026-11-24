"""
tests/jobs/conftest.py : fixtures des tests de la file d'attente et du worker.
"""

import mongomock
import pytest

import worker
from modules.apprentissage import etape_patching


@pytest.fixture(autouse=True)
def dossier_de_suivi_temporaire(monkeypatch, tmp_path):
    """
    Place les fichiers de suivi du patching dans un dossier temporaire.

    Le dossier suivi_patching/ est un chemin absolu (voir modules/config.py) :
    sans cette fixture, les tests écriraient dans le vrai dossier du projet.
    Le worker et etape_patching ont chacun leur copie de la constante.
    """
    dossier = tmp_path / "suivi_patching"
    monkeypatch.setattr(etape_patching, "DOSSIER_SUIVI", dossier)
    monkeypatch.setattr(worker, "DOSSIER_SUIVI", dossier)


@pytest.fixture
def jobs():
    """
    Collection "jobs" factice (en mémoire), vide.
    Chaque test reçoit une collection neuve : les tests sont indépendants.
    """
    return mongomock.MongoClient().db.jobs