"""
tests/jobs/test_service_calcul.py : tests de la détection d'un worker arrêté
(modules/etat_gpus.py) et des messages affichés dans l'interface
(ui/apprentissage/alerte_service.py).

Aucune connexion à MongoDB n'est ouverte : la collection est une fausse
collection mongomock.
"""

from datetime import datetime, timedelta, timezone

import pytest

from modules import etat_gpus
from ui.apprentissage import alerte_service


@pytest.fixture
def etat(jobs):
    """La collection "etat_worker" factice, dans la même base que "jobs"."""
    return jobs.database[etat_gpus.NOM_COLLECTION_ETAT_WORKER]


# ---------------------------------------------------------------------------
# Détection d'un worker arrêté
# ---------------------------------------------------------------------------

def test_worker_jamais_lance_est_inactif(etat):
    """Sans aucune publication, le worker est considéré comme arrêté."""
    assert etat_gpus.worker_est_actif(etat) is False


def test_worker_qui_vient_de_publier_est_actif(etat):
    """Une publication récente prouve que le worker est en vie."""
    etat_gpus.publier_etat_gpus(etat, [])

    assert etat_gpus.worker_est_actif(etat) is True


def test_worker_silencieux_depuis_trop_longtemps_est_inactif(etat):
    """Passé le délai, le worker est considéré comme arrêté."""
    ancien = datetime.now(timezone.utc) - timedelta(
        seconds=etat_gpus.DELAI_WORKER_ACTIF + 5
    )
    etat.insert_one({"_id": etat_gpus.ID_DOCUMENT_GPUS, "gpus": [], "maj_le": ancien})

    assert etat_gpus.worker_est_actif(etat) is False


def test_worker_sans_fuseau_horaire_est_bien_lu(etat):
    """MongoDB renvoie des dates sans fuseau : elles sont lues comme de l'UTC."""
    recent = datetime.now(timezone.utc).replace(tzinfo=None)
    etat.insert_one({"_id": etat_gpus.ID_DOCUMENT_GPUS, "gpus": [], "maj_le": recent})

    assert etat_gpus.worker_est_actif(etat) is True


# ---------------------------------------------------------------------------
# Messages de l'interface
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("situation", list(alerte_service.MESSAGES))
def test_chaque_message_est_complet(situation):
    """Chaque situation a un niveau valide et un texte qui indique quoi faire."""
    niveau, texte = alerte_service.message_service_arrete(situation)

    assert niveau in ("warning", "error")
    assert alerte_service.CONSEIL in texte


@pytest.mark.parametrize("situation", list(alerte_service.MESSAGES))
def test_les_messages_evitent_le_vocabulaire_technique(situation):
    """Les utilisateurs ne connaissent pas le mot "worker" : il n'apparaît pas."""
    _, texte = alerte_service.message_service_arrete(situation)

    assert "worker" not in texte.lower()


def test_une_situation_inconnue_est_signalee():
    """Une faute de frappe dans le nom de la situation ne passe pas inaperçue."""
    with pytest.raises(KeyError):
        alerte_service.message_service_arrete("inconnue")