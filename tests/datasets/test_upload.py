"""
tests/datasets/test_upload.py : tests de modules/datasets/upload.py

Les archives zip sont fabriquées en mémoire (fixture fabriquer_zip) et le
serveur est un faux serveur SFTP en mémoire (voir conftest.py). La base est
une fausse collection mongomock (fixture users).
"""

import io
import zipfile
from types import SimpleNamespace

import pytest

from modules.datasets import upload


@pytest.fixture(autouse=True)
def racine_de_test(monkeypatch):
    """Racine des datasets fixée à /data pour tous les tests de ce fichier."""
    monkeypatch.setattr(upload, "DATASETS_REMOTE_PATH", "/data")


def _archive_factice(noms):
    """
    Fausse archive qui ne contient que des noms de fichiers.
    Utile pour tester des chemins que zipfile ne permet pas de fabriquer
    de façon fiable sur tous les systèmes (par exemple avec un antislash).
    """
    infos = [SimpleNamespace(filename=nom) for nom in noms]
    return SimpleNamespace(infolist=lambda: infos)


# -------------------------------------------------------------- nom_valide


@pytest.mark.parametrize("nom", ["mon-dataset_1", "ABC", "a", "2024_run-3"])
def test_nom_valide_accepte(nom):
    assert upload.nom_valide(nom) is True


@pytest.mark.parametrize(
    "nom", ["", None, "../x", "a/b", "a b", "a.b", "é", "..", "a\\b"]
)
def test_nom_valide_refuse(nom):
    assert upload.nom_valide(nom) is False


# ---------------------------------------------------- chemins utilisateur


def test_dossier_utilisateur():
    assert upload.dossier_utilisateur("alice") == "/data/alice"


def test_dossier_utilisateur_racine_avec_slash_final(monkeypatch):
    monkeypatch.setattr(upload, "DATASETS_REMOTE_PATH", "/data/")
    assert upload.dossier_utilisateur("alice") == "/data/alice"


def test_chemin_dataset_utilisateur():
    assert upload.chemin_dataset_utilisateur("alice", "ds1") == "/data/alice/ds1"


# ----------------------------------------------------- ajouter_dataset_acces


def test_ajouter_dataset_acces(users, creer_compte):
    creer_compte("alice")
    upload.ajouter_dataset_acces(users, "alice", "/data/alice/ds1")
    compte = users.find_one({"username": "alice"})
    assert compte["datasets_access"] == ["/data/alice/ds1"]


def test_ajouter_dataset_acces_sans_doublon(users, creer_compte):
    creer_compte("alice")
    upload.ajouter_dataset_acces(users, "alice", "/data/alice/ds1")
    upload.ajouter_dataset_acces(users, "alice", "/data/alice/ds1")
    compte = users.find_one({"username": "alice"})
    assert compte["datasets_access"] == ["/data/alice/ds1"]


def test_ajouter_dataset_acces_plusieurs_chemins(users, creer_compte):
    creer_compte("alice")
    upload.ajouter_dataset_acces(users, "alice", "/data/alice/ds1")
    upload.ajouter_dataset_acces(users, "alice", "/data/alice/ds2")
    compte = users.find_one({"username": "alice"})
    assert compte["datasets_access"] == ["/data/alice/ds1", "/data/alice/ds2"]


def test_ajouter_dataset_acces_utilisateur_inconnu(users):
    # Aucune erreur, et aucun compte n'est créé par accident
    upload.ajouter_dataset_acces(users, "fantome", "/data/fantome/ds1")
    assert users.count_documents({}) == 0


# ------------------------------------------------------ dossiers distants


def test_creer_dossier_distant_cree_les_parents(faux_sftp):
    upload.creer_dossier_distant(faux_sftp, "/a/b/c")
    assert {"/a", "/a/b", "/a/b/c"} <= faux_sftp.dossiers


def test_creer_dossier_distant_deja_existant(faux_sftp):
    faux_sftp.ajouter_fichier("/a/b/fichier.txt", b"x")
    # Pas d'erreur, et le contenu existant n'est pas touché
    upload.creer_dossier_distant(faux_sftp, "/a/b")
    assert faux_sftp.fichiers["/a/b/fichier.txt"] == b"x"


def test_supprimer_dossier_distant_recursif(faux_sftp):
    faux_sftp.ajouter_fichier("/x/g.txt")
    faux_sftp.ajouter_fichier("/x/sous/dossier/f.txt")
    faux_sftp.ajouter_fichier("/autre/garde.txt")

    upload.supprimer_dossier_distant(faux_sftp, "/x")

    assert "/x" not in faux_sftp.dossiers
    assert not any(f.startswith("/x/") for f in faux_sftp.fichiers)
    # Un dossier voisin n'est pas touché
    assert "/autre/garde.txt" in faux_sftp.fichiers


# ------------------------------------------------------- _preparer_entrees


def _relatifs(entrees):
    """Extrait les chemins relatifs d'une liste (info_zip, chemin_relatif)."""
    return [relatif for _, relatif in entrees]


def test_preparer_entrees_archive_vide(fabriquer_zip):
    archive = zipfile.ZipFile(fabriquer_zip({}))
    assert upload._preparer_entrees(archive) == (None, "L'archive est vide.")


def test_preparer_entrees_ignore_les_fichiers_macos(fabriquer_zip):
    archive = zipfile.ZipFile(
        fabriquer_zip(
            {
                "Train/HSI/a.bil": b"",
                "__MACOSX/Train/._a.bil": b"",
                "Train/.DS_Store": b"",
            }
        )
    )
    entrees, erreur = upload._preparer_entrees(archive)
    assert erreur is None
    assert _relatifs(entrees) == ["Train/HSI/a.bil"]


def test_preparer_entrees_retire_le_dossier_englobant(fabriquer_zip):
    archive = zipfile.ZipFile(
        fabriquer_zip({"mon_ds/Train/a.bil": b"", "mon_ds/Test/b.bil": b""})
    )
    entrees, erreur = upload._preparer_entrees(archive)
    assert erreur is None
    assert _relatifs(entrees) == ["Train/a.bil", "Test/b.bil"]


def test_preparer_entrees_ignore_l_entree_du_dossier_englobant(fabriquer_zip):
    archive = zipfile.ZipFile(
        fabriquer_zip({"mon_ds/Train/a.bil": b""}, dossiers=["mon_ds"])
    )
    entrees, erreur = upload._preparer_entrees(archive)
    assert erreur is None
    assert _relatifs(entrees) == ["Train/a.bil"]


@pytest.mark.parametrize("nom_split", ["Train", "Test", "Val", "train"])
def test_preparer_entrees_conserve_un_dossier_de_split(fabriquer_zip, nom_split):
    # Un dossier Train, Test ou Val n'est jamais retiré, même s'il est seul
    archive = zipfile.ZipFile(fabriquer_zip({f"{nom_split}/a.bil": b""}))
    entrees, erreur = upload._preparer_entrees(archive)
    assert erreur is None
    assert _relatifs(entrees) == [f"{nom_split}/a.bil"]


@pytest.mark.parametrize(
    "chemin_dangereux",
    [
        "../evil.txt",
        "/etc/passwd",
        "Train/../../evil.txt",
        "Train\\evil.bil",
    ],
)
def test_preparer_entrees_refuse_les_chemins_dangereux(chemin_dangereux):
    # Protection "zip slip" : on ajoute un fichier normal à côté, pour qu'il
    # n'y ait pas de dossier englobant commun à retirer
    archive = _archive_factice(["Train/a.bil", chemin_dangereux])
    entrees, erreur = upload._preparer_entrees(archive)
    assert entrees is None
    assert erreur.startswith("L'archive contient un chemin non autorisé")
    assert chemin_dangereux in erreur


# ------------------------------------------------------------ envoyer_zip


def test_envoyer_zip_succes(brancher_sftp, fabriquer_zip):
    fichier = fabriquer_zip(
        {"Train/HSI/a.bil": b"cube", "Train/HSI/a.bil.hdr": b"entete"}
    )
    succes, message, chemin = upload.envoyer_zip(fichier, "alice", "ds1")

    assert succes is True
    assert chemin == "/data/alice/ds1"
    assert "ds1" in message
    assert "2 éléments" in message
    assert brancher_sftp.fichiers["/data/alice/ds1/Train/HSI/a.bil"] == b"cube"
    assert brancher_sftp.fichiers["/data/alice/ds1/Train/HSI/a.bil.hdr"] == b"entete"


def test_envoyer_zip_cree_les_dossiers_de_l_archive(brancher_sftp, fabriquer_zip):
    fichier = fabriquer_zip({}, dossiers=["Train", "Train/HSI"])
    # Une archive qui ne contient que des dossiers est acceptée
    succes, _, _ = upload.envoyer_zip(fichier, "alice", "ds1")
    assert succes is True
    assert "/data/alice/ds1/Train/HSI" in brancher_sftp.dossiers


def test_envoyer_zip_retire_le_dossier_englobant(brancher_sftp, fabriquer_zip):
    fichier = fabriquer_zip({"mon_ds/Train/a.bil": b"cube"})
    succes, _, _ = upload.envoyer_zip(fichier, "alice", "ds1")
    assert succes is True
    assert "/data/alice/ds1/Train/a.bil" in brancher_sftp.fichiers


def test_envoyer_zip_nom_de_dataset_invalide(brancher_sftp, fabriquer_zip):
    fichier = fabriquer_zip({"Train/a.bil": b""})
    succes, message, chemin = upload.envoyer_zip(fichier, "alice", "../x")
    assert succes is False
    assert chemin is None
    assert message.startswith("Nom invalide")
    # Rien n'a été écrit sur le serveur
    assert brancher_sftp.fichiers == {}


def test_envoyer_zip_nom_d_utilisateur_invalide(brancher_sftp, fabriquer_zip):
    fichier = fabriquer_zip({"Train/a.bil": b""})
    succes, message, chemin = upload.envoyer_zip(fichier, "al/ice", "ds1")
    assert succes is False
    assert chemin is None
    assert message == "Le nom d'utilisateur ne peut pas servir de nom de dossier."
    assert brancher_sftp.fichiers == {}


def test_envoyer_zip_fichier_non_zip(brancher_sftp):
    succes, message, chemin = upload.envoyer_zip(
        io.BytesIO(b"ceci n'est pas un zip"), "alice", "ds1"
    )
    assert succes is False
    assert chemin is None
    assert message == "Le fichier n'est pas une archive zip valide."


def test_envoyer_zip_archive_vide(brancher_sftp, fabriquer_zip):
    succes, message, chemin = upload.envoyer_zip(fabriquer_zip({}), "alice", "ds1")
    assert succes is False
    assert chemin is None
    assert message == "L'archive est vide."


def test_envoyer_zip_archive_suspecte_rien_n_est_ecrit(brancher_sftp, fabriquer_zip):
    # Le contrôle de l'archive se fait avant tout envoi
    fichier = fabriquer_zip({"Train/a.bil": b"cube", "../evil.txt": b"danger"})
    succes, message, chemin = upload.envoyer_zip(fichier, "alice", "ds1")

    assert succes is False
    assert chemin is None
    assert "chemin non autorisé" in message
    assert brancher_sftp.fichiers == {}
    assert "/data" not in brancher_sftp.dossiers


def test_envoyer_zip_serveur_injoignable(serveur_injoignable, fabriquer_zip):
    fichier = fabriquer_zip({"Train/a.bil": b""})
    succes, message, chemin = upload.envoyer_zip(fichier, "alice", "ds1")
    assert succes is False
    assert chemin is None
    assert message == "Serveur injoignable. Réessayez dans un instant."


def test_envoyer_zip_refuse_d_ecraser_un_dataset(brancher_sftp, fabriquer_zip):
    brancher_sftp.ajouter_fichier("/data/alice/ds1/ancien.txt", b"ancien")
    fichier = fabriquer_zip({"Train/a.bil": b"nouveau"})

    succes, message, chemin = upload.envoyer_zip(fichier, "alice", "ds1")

    assert succes is False
    assert chemin is None
    assert message == "Un dataset portant ce nom existe déjà."
    # Le dataset existant est intact
    assert brancher_sftp.fichiers["/data/alice/ds1/ancien.txt"] == b"ancien"
    assert "/data/alice/ds1/Train/a.bil" not in brancher_sftp.fichiers


def test_envoyer_zip_nettoie_apres_une_erreur_d_envoi(brancher_sftp, fabriquer_zip):
    # Le deuxième fichier échoue : le premier, déjà envoyé, doit disparaître
    brancher_sftp.echec_envoi_de = "b.bil"
    fichier = fabriquer_zip({"Train/a.bil": b"1", "Train/b.bil": b"2"})

    succes, message, chemin = upload.envoyer_zip(fichier, "alice", "ds1")

    assert succes is False
    assert chemin is None
    assert message.startswith("L'envoi a échoué")
    assert "Coupure simulée" in message
    assert "/data/alice/ds1" not in brancher_sftp.dossiers
    assert not any(f.startswith("/data/alice/ds1") for f in brancher_sftp.fichiers)


def test_envoyer_zip_peut_reessayer_apres_un_echec(brancher_sftp, fabriquer_zip):
    brancher_sftp.echec_envoi_de = "b.bil"
    contenu = {"Train/a.bil": b"1", "Train/b.bil": b"2"}
    upload.envoyer_zip(fabriquer_zip(contenu), "alice", "ds1")

    # Le nettoyage permet de réessayer avec le même nom, une fois la panne passée
    brancher_sftp.echec_envoi_de = None
    succes, _, _ = upload.envoyer_zip(fabriquer_zip(contenu), "alice", "ds1")
    assert succes is True


# -------------------------------------------------------- ajouter_dataset


def test_ajouter_dataset_donne_l_acces_apres_un_succes(
    users, creer_compte, brancher_sftp, fabriquer_zip
):
    creer_compte("alice")
    fichier = fabriquer_zip({"Train/a.bil": b"cube"})

    succes, message = upload.ajouter_dataset(users, fichier, "alice", "ds1")

    assert succes is True
    assert "ds1" in message
    compte = users.find_one({"username": "alice"})
    assert compte["datasets_access"] == ["/data/alice/ds1"]


def test_ajouter_dataset_pas_d_acces_si_l_envoi_echoue(
    users, creer_compte, brancher_sftp, fabriquer_zip
):
    creer_compte("alice")
    fichier = fabriquer_zip({"Train/a.bil": b"cube"})

    succes, _ = upload.ajouter_dataset(users, fichier, "alice", "../x")

    assert succes is False
    assert users.find_one({"username": "alice"})["datasets_access"] == []


def test_ajouter_dataset_deux_fois_le_meme_nom(
    users, creer_compte, brancher_sftp, fabriquer_zip
):
    creer_compte("alice")
    contenu = {"Train/a.bil": b"cube"}
    upload.ajouter_dataset(users, fabriquer_zip(contenu), "alice", "ds1")

    # Le second envoi est refusé et ne duplique pas l'accès
    succes, message = upload.ajouter_dataset(users, fabriquer_zip(contenu), "alice", "ds1")

    assert succes is False
    assert message == "Un dataset portant ce nom existe déjà."
    compte = users.find_one({"username": "alice"})
    assert compte["datasets_access"] == ["/data/alice/ds1"]