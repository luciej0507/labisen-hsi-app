"""
tests/datasets/conftest.py : fixtures propres aux tests de modules/datasets/.

Ce fichier s'ajoute à tests/conftest.py : les fixtures `users` et
`creer_compte` restent disponibles ici.

Il fournit un faux serveur SFTP en mémoire, pour tester sans jamais se
connecter au vrai serveur de l'école.
"""

import io
import posixpath
import zipfile
from stat import S_IFDIR, S_IFREG
from types import SimpleNamespace

import pytest

# Modules qui importent obtenir_sftp par son nom : c'est dans chacun d'eux
# qu'il faut le remplacer (et non dans sftp.py)
MODULES_UTILISANT_SFTP = ("stats", "upload", "exploration_dataset")


class FauxSFTP:
    """
    Faux client SFTP qui garde tout en mémoire.

    Il imite uniquement les méthodes utilisées par modules/datasets/ :
    listdir, listdir_attr, stat, mkdir, open, putfo, remove et rmdir.
    Les erreurs sont des IOError, comme avec paramiko.
    """

    def __init__(self):
        # Ensemble des dossiers existants (la racine existe toujours)
        self.dossiers = {"/"}
        # Fichiers existants : {chemin: contenu en octets}
        self.fichiers = {}
        # Si renseigné, l'envoi d'un fichier dont le chemin se termine par
        # ce texte échoue (sert à simuler une coupure pendant un envoi)
        self.echec_envoi_de = None

    # ----- Méthodes d'aide, utilisées par les tests pour préparer le décor

    def ajouter_dossier(self, chemin):
        """Crée un dossier et tous ses parents."""
        courant = ""
        for morceau in posixpath.normpath(chemin).strip("/").split("/"):
            courant += "/" + morceau
            self.dossiers.add(courant)

    def ajouter_fichier(self, chemin, contenu=b""):
        """Crée un fichier (et ses dossiers parents s'ils manquent)."""
        chemin = posixpath.normpath(chemin)
        self.ajouter_dossier(posixpath.dirname(chemin))
        self.fichiers[chemin] = contenu

    def _enfants(self, chemin):
        """Renvoie {nom: est_dossier} pour le contenu direct d'un dossier."""
        chemin = posixpath.normpath(chemin)
        if chemin not in self.dossiers:
            raise IOError("Dossier introuvable : " + chemin)
        enfants = {}
        for dossier in self.dossiers:
            if dossier != chemin and posixpath.dirname(dossier) == chemin:
                enfants[posixpath.basename(dossier)] = True
        for fichier in self.fichiers:
            if posixpath.dirname(fichier) == chemin:
                enfants[posixpath.basename(fichier)] = False
        return enfants

    # ----- Méthodes qui imitent paramiko.SFTPClient

    def listdir(self, chemin):
        return list(self._enfants(chemin))

    def listdir_attr(self, chemin):
        return [
            SimpleNamespace(
                filename=nom, st_mode=S_IFDIR if est_dossier else S_IFREG
            )
            for nom, est_dossier in self._enfants(chemin).items()
        ]

    def stat(self, chemin):
        chemin = posixpath.normpath(chemin)
        if chemin in self.dossiers:
            return SimpleNamespace(st_mode=S_IFDIR)
        if chemin in self.fichiers:
            return SimpleNamespace(st_mode=S_IFREG)
        raise IOError("Introuvable : " + chemin)

    def mkdir(self, chemin):
        chemin = posixpath.normpath(chemin)
        # Comme sur un vrai serveur : le parent doit exister et le dossier
        # ne doit pas exister déjà
        if posixpath.dirname(chemin) not in self.dossiers:
            raise IOError("Parent introuvable : " + chemin)
        if chemin in self.dossiers or chemin in self.fichiers:
            raise IOError("Existe déjà : " + chemin)
        self.dossiers.add(chemin)

    def open(self, chemin, mode="r"):
        chemin = posixpath.normpath(chemin)
        if chemin not in self.fichiers:
            raise IOError("Fichier introuvable : " + chemin)
        # BytesIO sait se lire et s'utiliser dans un "with"
        return io.BytesIO(self.fichiers[chemin])

    def putfo(self, source, cible):
        cible = posixpath.normpath(cible)
        if posixpath.dirname(cible) not in self.dossiers:
            raise IOError("Parent introuvable : " + cible)
        if self.echec_envoi_de and cible.endswith(self.echec_envoi_de):
            raise OSError("Coupure simulée pendant l'envoi")
        self.fichiers[cible] = source.read()

    def remove(self, chemin):
        chemin = posixpath.normpath(chemin)
        if chemin not in self.fichiers:
            raise IOError("Fichier introuvable : " + chemin)
        del self.fichiers[chemin]

    def rmdir(self, chemin):
        chemin = posixpath.normpath(chemin)
        # Un dossier non vide ne peut pas être supprimé
        if self._enfants(chemin):
            raise IOError("Dossier non vide : " + chemin)
        self.dossiers.discard(chemin)


@pytest.fixture
def faux_sftp():
    """Faux serveur SFTP vide, neuf pour chaque test."""
    return FauxSFTP()


@pytest.fixture
def brancher_sftp(monkeypatch, faux_sftp):
    """
    Fait en sorte que stats, upload et exploration_dataset utilisent le
    faux serveur à la place du vrai. Renvoie le faux serveur.
    """
    for module in MODULES_UTILISANT_SFTP:
        monkeypatch.setattr(
            f"modules.datasets.{module}.obtenir_sftp", lambda: faux_sftp
        )
    return faux_sftp


@pytest.fixture
def serveur_injoignable(monkeypatch):
    """Simule un serveur éteint : obtenir_sftp lève une OSError."""

    def _echec():
        raise OSError("Serveur injoignable")

    for module in MODULES_UTILISANT_SFTP:
        monkeypatch.setattr(f"modules.datasets.{module}.obtenir_sftp", _echec)


@pytest.fixture
def fabriquer_zip():
    """
    Fournit une fonction qui construit une archive zip en mémoire.

    Utilisation : fabriquer_zip({"Train/a.bil": b"..."}, dossiers=["Train"])
    Le résultat se passe directement à zipfile.ZipFile ou à envoyer_zip.
    """

    def _fabriquer(fichiers: dict, dossiers=()):
        tampon = io.BytesIO()
        with zipfile.ZipFile(tampon, "w") as archive:
            # Un nom qui se termine par "/" crée une entrée de dossier
            for dossier in dossiers:
                archive.writestr(dossier.rstrip("/") + "/", b"")
            for nom, contenu in fichiers.items():
                archive.writestr(nom, contenu)
        tampon.seek(0)
        return tampon

    return _fabriquer


@pytest.fixture
def creer_dataset(faux_sftp):
    """
    Fournit une fonction qui crée un dataset conforme sur le faux serveur.

    Utilisation : creer_dataset("/ds", {"Train": ["a", "b"], "Test": ["c"]})
    Chaque cube reçoit son .bil, son .bil.hdr, sa photo RGB et son masque
    d'annotation. Les options hdr, rgb et annotes à False retirent la
    famille de fichiers correspondante, pour simuler des fichiers manquants.
    """

    def _creer(racine, cubes_par_split, hdr=True, rgb=True, annotes=True):
        for split, cubes in cubes_par_split.items():
            base = f"{racine}/{split}"
            # Le dossier du split existe même s'il ne contient aucun cube
            faux_sftp.ajouter_dossier(base)
            for cube in cubes:
                faux_sftp.ajouter_fichier(f"{base}/HSI/{cube}.bil")
                if hdr:
                    faux_sftp.ajouter_fichier(f"{base}/HSI/{cube}.bil.hdr")
                if rgb:
                    faux_sftp.ajouter_fichier(f"{base}/RGB/{cube}.png")
                if annotes:
                    faux_sftp.ajouter_fichier(
                        f"{base}/Annotation/PNG/{cube}.png"
                    )

    return _creer