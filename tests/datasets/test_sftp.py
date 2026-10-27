"""
tests/datasets/test_sftp.py : tests de modules/datasets/sftp.py

Aucune connexion réelle n'est ouverte : le socket et paramiko sont remplacés
par de faux objets, et le faux serveur SFTP du conftest sert aux fonctions
qui parcourent des dossiers.
"""

from types import SimpleNamespace

import paramiko
import pytest

from modules.datasets import sftp


class FauxTransport:
    """Faux transport paramiko : se "connecte" sans rien faire."""

    def __init__(self, sock):
        self.actif = True

    def connect(self, username=None, password=None):
        pass

    def is_active(self):
        return self.actif


@pytest.fixture(autouse=True)
def etat_propre(monkeypatch):
    """
    Remet à zéro la connexion partagée avant chaque test (et la restaure
    après), pour que les tests ne s'influencent pas entre eux.
    """
    monkeypatch.setitem(sftp._connexion, "sftp", None)
    monkeypatch.setitem(sftp._connexion, "transport", None)
    monkeypatch.setitem(sftp._dernier_echec, "heure", None)


@pytest.fixture
def faux_reseau(monkeypatch):
    """
    Remplace le socket et paramiko par de faux objets qui réussissent.
    Renvoie la liste des tentatives de connexion (une entrée par appel).
    """
    tentatives = []

    def faux_create_connection(adresse, timeout=None):
        tentatives.append(adresse)
        return object()

    monkeypatch.setattr(sftp.socket, "create_connection", faux_create_connection)
    monkeypatch.setattr(sftp.paramiko, "Transport", FauxTransport)
    monkeypatch.setattr(
        sftp.paramiko.SFTPClient, "from_transport", lambda transport: object()
    )
    return tentatives


# ---------------------------------------------------------------- trouver


def test_trouver_nom_exact_sans_tenir_compte_de_la_casse():
    assert sftp.trouver(["Train", "Test"], "train") == "Train"
    assert sftp.trouver(["TRAIN"], "Train") == "TRAIN"


def test_trouver_dossier_absent():
    assert sftp.trouver(["Train", "Test"], "Val") is None


def test_trouver_prefixe_accepte_pour_hsi():
    assert sftp.trouver(["RGB", "HSI-Hybercube"], "HSI") == "HSI-Hybercube"


def test_trouver_nom_exact_prioritaire_sur_le_prefixe():
    assert sftp.trouver(["HSI-Hybercube", "hsi"], "HSI") == "hsi"


def test_trouver_prefixe_donne_un_resultat_stable():
    # Parmi plusieurs candidats, c'est le premier par ordre alphabétique
    assert sftp.trouver(["HSI-b", "HSI-a"], "HSI") == "HSI-a"


def test_trouver_pas_de_prefixe_pour_les_autres_dossiers():
    # Seuls les dossiers de DOSSIERS_A_PREFIXE acceptent un suffixe
    assert sftp.trouver(["Training"], "Train") is None


# ------------------------------------------------------------ lister_noms


def test_lister_noms_dossier_existant(faux_sftp):
    faux_sftp.ajouter_fichier("/data/a.txt")
    faux_sftp.ajouter_dossier("/data/sous")
    assert sorted(sftp.lister_noms(faux_sftp, "/data")) == ["a.txt", "sous"]


def test_lister_noms_dossier_inaccessible(faux_sftp):
    assert sftp.lister_noms(faux_sftp, "/nexiste/pas") is None


# --------------------------------------------------------------- resoudre


def test_resoudre_tolere_les_differences_de_casse(faux_sftp):
    faux_sftp.ajouter_dossier("/data/ds/Annotation/JSON")
    chemin = sftp.resoudre(faux_sftp, "/data/ds", "annotation/json")
    assert chemin == "/data/ds/Annotation/JSON"


def test_resoudre_base_avec_slash_final(faux_sftp):
    faux_sftp.ajouter_dossier("/data/ds/Annotation")
    assert sftp.resoudre(faux_sftp, "/data/ds/", "Annotation") == "/data/ds/Annotation"


def test_resoudre_dossier_intermediaire_absent(faux_sftp):
    faux_sftp.ajouter_dossier("/data/ds/Annotation")
    assert sftp.resoudre(faux_sftp, "/data/ds", "Annotation/JSON") is None


def test_resoudre_base_inaccessible(faux_sftp):
    assert sftp.resoudre(faux_sftp, "/nexiste/pas", "HSI") is None


def test_resoudre_accepte_le_prefixe_hsi(faux_sftp):
    faux_sftp.ajouter_dossier("/data/ds/HSI-Hybercube")
    assert sftp.resoudre(faux_sftp, "/data/ds", "HSI") == "/data/ds/HSI-Hybercube"


# ----------------------------------------------------------- obtenir_sftp


def test_connexion_inactive_au_depart():
    assert sftp._connexion_active() is False


def test_premier_appel_ouvre_une_connexion(faux_reseau):
    assert sftp.obtenir_sftp() is not None
    assert len(faux_reseau) == 1


def test_connexion_reutilisee_si_elle_est_active(faux_reseau):
    premier = sftp.obtenir_sftp()
    second = sftp.obtenir_sftp()
    assert premier is second
    # Une seule connexion ouverte pour les deux appels
    assert len(faux_reseau) == 1


def test_nouvelle_connexion_si_le_transport_est_coupe(faux_reseau):
    sftp.obtenir_sftp()
    # On simule une connexion coupée par le serveur
    sftp._connexion["transport"].actif = False
    sftp.obtenir_sftp()
    assert len(faux_reseau) == 2


def test_echec_recent_pas_de_nouvelle_tentative(monkeypatch):
    tentatives = []

    def echec(adresse, timeout=None):
        tentatives.append(adresse)
        raise OSError("Serveur éteint")

    monkeypatch.setattr(sftp.socket, "create_connection", echec)

    with pytest.raises(OSError):
        sftp.obtenir_sftp()
    # Deuxième appel : l'erreur est levée tout de suite, sans réessayer
    with pytest.raises(OSError, match="échec récent"):
        sftp.obtenir_sftp()
    assert len(tentatives) == 1


def test_nouvelle_tentative_possible_apres_le_delai(monkeypatch, faux_reseau):
    # Horloge factice : on fait avancer le temps à la main
    horloge = [1000.0]
    monkeypatch.setattr(sftp, "time", SimpleNamespace(time=lambda: horloge[0]))

    connexion_ok = sftp.socket.create_connection

    def echec(adresse, timeout=None):
        raise OSError("Serveur éteint")

    # Premier appel : échec, l'heure de l'échec est retenue
    monkeypatch.setattr(sftp.socket, "create_connection", echec)
    with pytest.raises(OSError):
        sftp.obtenir_sftp()
    assert sftp._dernier_echec["heure"] == 1000.0

    # Le serveur revient, mais le délai n'est pas écoulé : toujours refusé
    monkeypatch.setattr(sftp.socket, "create_connection", connexion_ok)
    horloge[0] += sftp.DELAI_NOUVELLE_TENTATIVE - 1
    with pytest.raises(OSError, match="échec récent"):
        sftp.obtenir_sftp()

    # Le délai est écoulé : la connexion réussit et l'échec est oublié
    horloge[0] += 2
    assert sftp.obtenir_sftp() is not None
    assert sftp._dernier_echec["heure"] is None


def test_echec_d_authentification_est_retenu(monkeypatch, faux_reseau):
    class TransportRefuse(FauxTransport):
        def connect(self, username=None, password=None):
            raise paramiko.SSHException("Authentification refusée")

    monkeypatch.setattr(sftp.paramiko, "Transport", TransportRefuse)

    with pytest.raises(paramiko.SSHException):
        sftp.obtenir_sftp()
    assert sftp._dernier_echec["heure"] is not None