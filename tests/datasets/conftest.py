"""
tests/datasets/conftest.py : fixtures propres aux tests de modules/datasets/.

Ce fichier s'ajoute à tests/conftest.py : les fixtures `users` et
`creer_compte` restent disponibles ici.

Il fournit un "faux disque" : de vrais dossiers et fichiers, créés dans un
dossier temporaire (tmp_path de pytest) qui est supprimé à la fin de chaque
test. Les tests écrivent des chemins logiques comme "/ds/Train/HSI/a.bil" ;
la fixture `disque` les place sous le dossier temporaire.
"""

import io
import os
import shutil
import zipfile
from pathlib import Path

import pytest


class Disque:
    """
    Petit assistant pour fabriquer et lire des fichiers dans un dossier
    temporaire.

    Un chemin logique commence par "/" (par exemple "/ds/Train/HSI/a.bil").
    Sur le disque, il se trouve sous la racine temporaire du test. La
    méthode chemin() donne le vrai chemin, à passer au code testé.
    """

    def __init__(self, racine: Path):
        self.racine = racine
        # Si renseigné, la copie d'un fichier dont le nom se termine par ce
        # texte échoue (sert à simuler une coupure pendant un envoi)
        self.echec_envoi_de = None

    # ----- Passage entre chemin logique et chemin réel

    def chemin(self, logique: str) -> str:
        """Renvoie le vrai chemin (texte) d'un chemin logique."""
        return str(self.racine) + logique

    def _logique(self, chemin: Path) -> str:
        """Renvoie le chemin logique d'un vrai chemin situé sous la racine."""
        return "/" + chemin.relative_to(self.racine).as_posix()

    # ----- Méthodes d'aide, utilisées par les tests pour préparer le décor

    def ajouter_dossier(self, logique: str):
        """Crée un dossier et tous ses parents."""
        Path(self.chemin(logique)).mkdir(parents=True, exist_ok=True)

    def ajouter_fichier(self, logique: str, contenu: bytes = b""):
        """Crée un fichier (et ses dossiers parents s'ils manquent)."""
        fichier = Path(self.chemin(logique))
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_bytes(contenu)

    # ----- Lecture de ce qui existe, pour les vérifications des tests

    @property
    def dossiers(self) -> set:
        """Ensemble des chemins logiques de tous les dossiers existants."""
        return {
            self._logique(chemin)
            for chemin in self.racine.rglob("*")
            if chemin.is_dir()
        }

    @property
    def fichiers(self) -> dict:
        """Dictionnaire {chemin logique: contenu en octets} de tous les fichiers."""
        return {
            self._logique(chemin): chemin.read_bytes()
            for chemin in self.racine.rglob("*")
            if chemin.is_file()
        }


@pytest.fixture
def disque(monkeypatch, tmp_path):
    """
    Faux disque neuf pour chaque test (un dossier temporaire vide).

    Si un test renseigne disque.echec_envoi_de, la copie d'un fichier dont
    le nom se termine par ce texte lève une OSError, comme une coupure.
    """
    le_disque = Disque(tmp_path)
    copie_normale = shutil.copyfileobj

    def copie_qui_peut_echouer(source, destination, *autres):
        cible = os.fspath(getattr(destination, "name", ""))
        if le_disque.echec_envoi_de and cible.endswith(le_disque.echec_envoi_de):
            raise OSError("Coupure simulée pendant l'envoi")
        copie_normale(source, destination, *autres)

    monkeypatch.setattr(shutil, "copyfileobj", copie_qui_peut_echouer)
    return le_disque


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
def creer_dataset(disque):
    """
    Fournit une fonction qui crée un dataset conforme sur le faux disque.

    Utilisation : creer_dataset("/ds", {"Train": ["a", "b"], "Test": ["c"]})
    Chaque cube reçoit son .bil, son .bil.hdr, sa photo RGB et son masque
    d'annotation. Les options hdr, rgb et annotes à False retirent la
    famille de fichiers correspondante, pour simuler des fichiers manquants.
    """

    def _creer(racine, cubes_par_split, hdr=True, rgb=True, annotes=True):
        for split, cubes in cubes_par_split.items():
            base = f"{racine}/{split}"
            # Le dossier du split existe même s'il ne contient aucun cube
            disque.ajouter_dossier(base)
            for cube in cubes:
                disque.ajouter_fichier(f"{base}/HSI/{cube}.bil")
                if hdr:
                    disque.ajouter_fichier(f"{base}/HSI/{cube}.bil.hdr")
                if rgb:
                    disque.ajouter_fichier(f"{base}/RGB/{cube}.png")
                if annotes:
                    disque.ajouter_fichier(f"{base}/Annotation/PNG/{cube}.png")

    return _creer
