"""
tests/datasets/test_stats.py : tests de modules/datasets/stats.py

Les fonctions etat_split et tache_split sont pures (pas de réseau).
Les autres lisent un faux serveur SFTP en mémoire (voir conftest.py).
"""

import pytest

from modules.datasets import stats


# ------------------------------------------------------------- etat_split


@pytest.mark.parametrize(
    "cubes_par_split, attendu",
    [
        ({"Train": 5, "Test": 2, "Val": 1}, "Fait"),
        ({"Train": 5, "Test": 0, "Val": 1}, "Incomplet"),
        ({"Train": 3}, "Incomplet"),
        ({"Train": 0, "Test": 0, "Val": 0}, "Non fait"),
        ({}, "Non fait"),
    ],
)
def test_etat_split(cubes_par_split, attendu):
    assert stats.etat_split(cubes_par_split) == attendu


# ------------------------------------------------------------ tache_split


def test_tache_split_fait():
    assert stats.tache_split({"Train": 1, "Test": 1, "Val": 1}) is None


def test_tache_split_non_fait():
    assert stats.tache_split({}) == "Split Train/Test/Val à faire"


def test_tache_split_dossier_absent():
    texte = stats.tache_split({"Train": 3, "Test": 2})
    assert texte == "Split incomplet (dossier absent : Val)"


def test_tache_split_dossier_vide():
    texte = stats.tache_split({"Train": 3, "Test": 2, "Val": 0})
    assert texte == "Split incomplet (dossier vide : Val)"


def test_tache_split_absent_et_vide():
    texte = stats.tache_split({"Train": 3, "Test": 0})
    assert texte == "Split incomplet (dossier absent : Val; dossier vide : Test)"


# -------------------------------------------------------------- _resultat


def test_resultat_additionne_les_splits():
    splits = {
        "Train": {"cubes": 3, "annotes": 2, "incomplets": 1, "ancienne_structure": False},
        "Test": {"cubes": 1, "annotes": 1, "incomplets": 0, "ancienne_structure": True},
    }
    resultat = stats._resultat("À compléter", splits)

    assert resultat["etat"] == "À compléter"
    assert resultat["cubes_par_split"] == {"Train": 3, "Test": 1}
    assert resultat["total_cubes"] == 4
    assert resultat["annotes"] == 3
    assert resultat["incomplets"] == 1
    assert resultat["ancienne_structure"] is True
    assert resultat["taches"] == []


def test_resultat_sans_split():
    resultat = stats._resultat("Introuvable")
    assert resultat["total_cubes"] == 0
    assert resultat["cubes_par_split"] == {}
    assert resultat["ancienne_structure"] is False


# ----------------------------------------------------------- _stats_split


def test_stats_split_dataset_conforme(faux_sftp, creer_dataset):
    creer_dataset("/ds", {"Train": ["a", "b"]})
    resultat = stats._stats_split(faux_sftp, "/ds/Train")
    assert resultat == {
        "cubes": 2,
        "annotes": 2,
        "incomplets": 0,
        "ancienne_structure": False,
    }


def test_stats_split_masque_manquant(faux_sftp, creer_dataset):
    creer_dataset("/ds", {"Train": ["a", "b"]}, annotes=False)
    resultat = stats._stats_split(faux_sftp, "/ds/Train")
    assert resultat["cubes"] == 2
    assert resultat["annotes"] == 0
    assert resultat["incomplets"] == 0


def test_stats_split_entete_manquant(faux_sftp, creer_dataset):
    creer_dataset("/ds", {"Train": ["a", "b"]}, hdr=False)
    assert stats._stats_split(faux_sftp, "/ds/Train")["incomplets"] == 2


def test_stats_split_photo_rgb_manquante(faux_sftp, creer_dataset):
    creer_dataset("/ds", {"Train": ["a", "b"]}, rgb=False)
    assert stats._stats_split(faux_sftp, "/ds/Train")["incomplets"] == 2


def test_stats_split_masque_a_plat_accepte(faux_sftp):
    # Masque directement dans Annotation/ (sans le sous-dossier PNG)
    faux_sftp.ajouter_fichier("/ds/Train/HSI/a.bil")
    faux_sftp.ajouter_fichier("/ds/Train/Annotation/a.png")
    assert stats._stats_split(faux_sftp, "/ds/Train")["annotes"] == 1


def test_stats_split_masque_a_plat_refuse(faux_sftp, monkeypatch):
    # La règle temporaire est désactivée
    monkeypatch.setattr(stats, "ACCEPTER_ANNOTATION_A_PLAT", False)
    faux_sftp.ajouter_fichier("/ds/Train/HSI/a.bil")
    faux_sftp.ajouter_fichier("/ds/Train/Annotation/a.png")
    assert stats._stats_split(faux_sftp, "/ds/Train")["annotes"] == 0


def test_stats_split_ancienne_structure_rgb(faux_sftp):
    # RGB contient encore un sous-dossier PNG : les photos sont ignorées,
    # donc le cube n'est pas compté comme incomplet à cause d'elles
    faux_sftp.ajouter_fichier("/ds/Train/HSI/a.bil")
    faux_sftp.ajouter_fichier("/ds/Train/HSI/a.bil.hdr")
    faux_sftp.ajouter_dossier("/ds/Train/RGB/PNG")
    resultat = stats._stats_split(faux_sftp, "/ds/Train")
    assert resultat["ancienne_structure"] is True
    assert resultat["incomplets"] == 0


def test_stats_split_sans_dossier_hsi(faux_sftp):
    faux_sftp.ajouter_dossier("/ds/Train")
    resultat = stats._stats_split(faux_sftp, "/ds/Train")
    assert resultat["cubes"] == 0


def test_stats_split_dossier_hsi_avec_suffixe(faux_sftp):
    faux_sftp.ajouter_fichier("/ds/Train/HSI-Hybercube/a.bil")
    assert stats._stats_split(faux_sftp, "/ds/Train")["cubes"] == 1


def test_stats_split_extensions_en_majuscules(faux_sftp):
    faux_sftp.ajouter_fichier("/ds/Train/HSI/a.BIL")
    assert stats._stats_split(faux_sftp, "/ds/Train")["cubes"] == 1


# --------------------------------------------------------- calculer_stats


def test_calculer_stats_serveur_injoignable(serveur_injoignable):
    resultat = stats.calculer_stats("/ds")
    assert resultat["etat"] == "Serveur injoignable"
    assert resultat["total_cubes"] == 0
    assert resultat["taches"] == []


def test_calculer_stats_dataset_introuvable(brancher_sftp):
    assert stats.calculer_stats("/nexiste/pas")["etat"] == "Introuvable"


def test_calculer_stats_dossier_sans_split(brancher_sftp):
    brancher_sftp.ajouter_dossier("/ds/Autre")
    assert stats.calculer_stats("/ds")["etat"] == "Non conforme"


def test_calculer_stats_dataset_complet(brancher_sftp, creer_dataset):
    creer_dataset("/ds", {"Train": ["a", "b"], "Test": ["c"], "Val": ["d"]})
    resultat = stats.calculer_stats("/ds")

    assert resultat["etat"] == "Complet"
    assert resultat["taches"] == []
    assert resultat["cubes_par_split"] == {"Train": 2, "Test": 1, "Val": 1}
    assert resultat["total_cubes"] == 4
    assert resultat["annotes"] == 4
    assert resultat["incomplets"] == 0


def test_calculer_stats_chemin_avec_slash_final(brancher_sftp, creer_dataset):
    creer_dataset("/ds", {"Train": ["a"], "Test": ["b"], "Val": ["c"]})
    assert stats.calculer_stats("/ds/")["etat"] == "Complet"


def test_calculer_stats_noms_de_splits_en_minuscules(brancher_sftp, creer_dataset):
    creer_dataset("/ds", {"train": ["a"], "test": ["b"], "val": ["c"]})
    resultat = stats.calculer_stats("/ds")
    assert resultat["etat"] == "Complet"
    # Les clés utilisent toujours les noms officiels des splits
    assert set(resultat["cubes_par_split"]) == {"Train", "Test", "Val"}


def test_calculer_stats_split_absent(brancher_sftp, creer_dataset):
    creer_dataset("/ds", {"Train": ["a", "b"]})
    resultat = stats.calculer_stats("/ds")
    assert resultat["etat"] == "À compléter"
    assert resultat["taches"] == ["Split incomplet (dossier absent : Test, Val)"]


def test_calculer_stats_split_vide(brancher_sftp, creer_dataset):
    creer_dataset("/ds", {"Train": ["a"], "Test": [], "Val": []})
    resultat = stats.calculer_stats("/ds")
    assert resultat["taches"] == ["Split incomplet (dossier vide : Test, Val)"]


def test_calculer_stats_plusieurs_taches_independantes(brancher_sftp, creer_dataset):
    # Entêtes et masques manquants, en plus des splits absents
    creer_dataset("/ds", {"Train": ["a", "b"]}, hdr=False, annotes=False)
    resultat = stats.calculer_stats("/ds")

    assert resultat["etat"] == "À compléter"
    assert resultat["taches"] == [
        "Split incomplet (dossier absent : Test, Val)",
        "2 cube(s) avec des fichiers manquants",
        "2 masque(s) d'annotation manquant(s)",
    ]


def test_calculer_stats_ancienne_structure(brancher_sftp, creer_dataset):
    creer_dataset("/ds", {"Train": ["a"], "Test": ["b"], "Val": ["c"]})
    brancher_sftp.ajouter_dossier("/ds/Train/RGB/PNG")
    resultat = stats.calculer_stats("/ds")

    assert resultat["etat"] == "À compléter"
    assert resultat["taches"] == [
        "Ancienne structure RGB à migrer (retirer les dossiers PNG et TIFF)"
    ]


# ----------------------------------------------------------- lister_cubes


def test_lister_cubes_tries_par_ordre_alphabetique(brancher_sftp, creer_dataset):
    creer_dataset("/ds", {"Train": ["c", "a", "b"]})
    assert stats.lister_cubes("/ds", "Train") == ["a", "b", "c"]


def test_lister_cubes_split_en_minuscules(brancher_sftp, creer_dataset):
    creer_dataset("/ds", {"train": ["a"]})
    assert stats.lister_cubes("/ds", "Train") == ["a"]


def test_lister_cubes_split_absent(brancher_sftp, creer_dataset):
    creer_dataset("/ds", {"Train": ["a"]})
    assert stats.lister_cubes("/ds", "Val") == []


def test_lister_cubes_dataset_introuvable(brancher_sftp):
    assert stats.lister_cubes("/nexiste/pas", "Train") == []


def test_lister_cubes_serveur_injoignable(serveur_injoignable):
    assert stats.lister_cubes("/ds", "Train") == []


# -------------------------------------------------------- lire_dimensions

ENTETE_VALIDE = b"ENVI\nsamples = 640\nlines   = 480\nbands = 224\n"


def test_lire_dimensions_entete_valide(brancher_sftp):
    brancher_sftp.ajouter_fichier("/ds/Train/HSI/a.bil.hdr", ENTETE_VALIDE)
    assert stats.lire_dimensions("/ds", "Train", "a") == {
        "lignes": 480,
        "colonnes": 640,
        "bandes": 224,
    }


def test_lire_dimensions_cles_en_majuscules(brancher_sftp):
    contenu = b"Samples = 10\nLINES = 20\nBands = 30\n"
    brancher_sftp.ajouter_fichier("/ds/Train/HSI/a.bil.hdr", contenu)
    assert stats.lire_dimensions("/ds", "Train", "a") == {
        "lignes": 20,
        "colonnes": 10,
        "bandes": 30,
    }


def test_lire_dimensions_nom_de_fichier_en_majuscules(brancher_sftp):
    brancher_sftp.ajouter_fichier("/ds/Train/HSI/A.BIL.HDR", ENTETE_VALIDE)
    assert stats.lire_dimensions("/ds", "Train", "a")["bandes"] == 224


def test_lire_dimensions_cle_manquante(brancher_sftp):
    brancher_sftp.ajouter_fichier(
        "/ds/Train/HSI/a.bil.hdr", b"samples = 640\nlines = 480\n"
    )
    assert stats.lire_dimensions("/ds", "Train", "a") is None


def test_lire_dimensions_valeur_non_numerique(brancher_sftp):
    contenu = b"samples = abc\nlines = 480\nbands = 224\n"
    brancher_sftp.ajouter_fichier("/ds/Train/HSI/a.bil.hdr", contenu)
    assert stats.lire_dimensions("/ds", "Train", "a") is None


def test_lire_dimensions_entete_absent(brancher_sftp):
    brancher_sftp.ajouter_fichier("/ds/Train/HSI/a.bil")
    assert stats.lire_dimensions("/ds", "Train", "a") is None


def test_lire_dimensions_split_absent(brancher_sftp):
    brancher_sftp.ajouter_dossier("/ds/Train")
    assert stats.lire_dimensions("/ds", "Val", "a") is None


def test_lire_dimensions_dossier_hsi_absent(brancher_sftp):
    brancher_sftp.ajouter_dossier("/ds/Train")
    assert stats.lire_dimensions("/ds", "Train", "a") is None


def test_lire_dimensions_serveur_injoignable(serveur_injoignable):
    assert stats.lire_dimensions("/ds", "Train", "a") is None