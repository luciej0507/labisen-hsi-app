"""
tests/datasets/test_chemins.py : tests de modules/datasets/chemins.py

Les fonctions qui parcourent des dossiers utilisent de vrais dossiers
temporaires (fixture disque, voir conftest.py).
"""

from modules.datasets import chemins


# ---------------------------------------------------------------- trouver


def test_trouver_nom_exact_sans_tenir_compte_de_la_casse():
    assert chemins.trouver(["Train", "Test"], "train") == "Train"
    assert chemins.trouver(["TRAIN"], "Train") == "TRAIN"


def test_trouver_dossier_absent():
    assert chemins.trouver(["Train", "Test"], "Val") is None


def test_trouver_prefixe_accepte_pour_hsi():
    assert chemins.trouver(["RGB", "HSI-Hybercube"], "HSI") == "HSI-Hybercube"


def test_trouver_nom_exact_prioritaire_sur_le_prefixe():
    assert chemins.trouver(["HSI-Hybercube", "hsi"], "HSI") == "hsi"


def test_trouver_prefixe_donne_un_resultat_stable():
    # Parmi plusieurs candidats, c'est le premier par ordre alphabétique
    assert chemins.trouver(["HSI-b", "HSI-a"], "HSI") == "HSI-a"


def test_trouver_pas_de_prefixe_pour_les_autres_dossiers():
    # Seuls les dossiers de DOSSIERS_A_PREFIXE acceptent un suffixe
    assert chemins.trouver(["Training"], "Train") is None


# ------------------------------------------------------------ lister_noms


def test_lister_noms_dossier_existant(disque):
    disque.ajouter_fichier("/data/a.txt")
    disque.ajouter_dossier("/data/sous")
    noms = chemins.lister_noms(disque.chemin("/data"))
    assert sorted(noms) == ["a.txt", "sous"]


def test_lister_noms_dossier_inaccessible(disque):
    assert chemins.lister_noms(disque.chemin("/nexiste/pas")) is None


def test_lister_noms_chemin_d_un_fichier(disque):
    # Un fichier n'est pas un dossier : il n'y a rien à lister
    disque.ajouter_fichier("/data/a.txt")
    assert chemins.lister_noms(disque.chemin("/data/a.txt")) is None


# --------------------------------------------------------------- resoudre


def test_resoudre_tolere_les_differences_de_casse(disque):
    disque.ajouter_dossier("/data/ds/Annotation/JSON")
    resultat = chemins.resoudre(disque.chemin("/data/ds"), "annotation/json")
    assert resultat == disque.chemin("/data/ds/Annotation/JSON")


def test_resoudre_base_avec_slash_final(disque):
    disque.ajouter_dossier("/data/ds/Annotation")
    resultat = chemins.resoudre(disque.chemin("/data/ds/"), "Annotation")
    assert resultat == disque.chemin("/data/ds/Annotation")


def test_resoudre_dossier_intermediaire_absent(disque):
    disque.ajouter_dossier("/data/ds/Annotation")
    assert chemins.resoudre(disque.chemin("/data/ds"), "Annotation/JSON") is None


def test_resoudre_base_inaccessible(disque):
    assert chemins.resoudre(disque.chemin("/nexiste/pas"), "HSI") is None


def test_resoudre_accepte_le_prefixe_hsi(disque):
    disque.ajouter_dossier("/data/ds/HSI-Hybercube")
    resultat = chemins.resoudre(disque.chemin("/data/ds"), "HSI")
    assert resultat == disque.chemin("/data/ds/HSI-Hybercube")
