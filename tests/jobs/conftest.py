"""
tests/jobs/conftest.py : fixtures des tests de la file d'attente et du worker.
"""

import mongomock
import pytest


@pytest.fixture
def jobs():
    """
    Collection "jobs" factice (en mémoire), vide.
    Chaque test reçoit une collection neuve : les tests sont indépendants.
    """
    return mongomock.MongoClient().db.jobs