"""
tests/datasets/test_stats.py : tests de modules/datasets/stats.py

Les fonctions etat_split et tache_split sont pures (pas d'accès au disque).
Les autres lisent de vrais dossiers temporaires (fixture disque, voir conftest.py).
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
        "Train": {"cubes": 3, "annotes": 2, "rgb": 2, "incomplets": 1, "ancienne_structure": False},
        "Test": {"cubes": 1, "annotes": 1, "rgb": 1, "incomplets": 0, "ancienne_structure": True},
    }
    resultat = stats._resultat("À compléter", splits)

    assert resultat["etat"] == "À compléter"
    assert resultat["cubes_par_split"] == {"Train": 3, "Test": 1}
    assert resultat["details_par_split"] == {
        "Train": {"cubes": 3, "annotes": 2, "rgb": 2},
        "Test": {"cubes": 1, "annotes": 1, "rgb": 1},
    }
    assert resultat["total_cubes"] == 4
    assert resultat["annotes"] == 3
    assert resultat["rgb"] == 3
    assert resultat["incomplets"] == 1
    assert resultat["ancienne_structure"] is True
    assert resultat["taches"] == []


def test_resultat_sans_split():
    resultat = stats._resultat("Introuvable")
    assert resultat["total_cubes"] == 0
    assert resultat["cubes_par_split"] == {}
    assert resultat["ancienne_structure"] is False


# ----------------------------------------------------------- _stats_split


def test_stats_split_dataset_conforme(disque, creer_dataset):
    creer_dataset("/ds", {"Train": ["a", "b"]})
    resultat = stats._stats_split(disque.chemin("/ds/Train"))
    assert resultat == {
        "cubes": 2,
        "annotes": 2,
        "rgb": 2,
        "incomplets": 0,
        "sans_masque": 0,
        "sans_hdr": 0,
        "sans_rgb": 0,
        "ancienne_structure": False,
    }

def test_stats_split_masque_manquant(disque, creer_dataset):
    creer_dataset("/ds", {"Train": ["a", "b"]}, annotes=False)
    resultat = stats._stats_split(disque.chemin("/ds/Train"))
    assert resultat["cubes"] == 2
    assert resultat["annotes"] == 0
    assert resultat["incomplets"] == 0


def test_stats_split_entete_manquant(disque, creer_dataset):
    creer_dataset("/ds", {"Train": ["a", "b"]}, hdr=False)
    assert stats._stats_split(disque.chemin("/ds/Train"))["incomplets"] == 2


def test_stats_split_photo_rgb_manquante(disque, creer_dataset):
    creer_dataset("/ds", {"Train": ["a", "b"]}, rgb=False)
    assert stats._stats_split(disque.chemin("/ds/Train"))["incomplets"] == 2


def test_stats_split_masque_a_plat_accepte(disque):
    # Masque directement dans Annotation/ (sans le sous-dossier PNG)
    disque.ajouter_fichier("/ds/Train/HSI/a.bil")
    disque.ajouter_fichier("/ds/Train/Annotation/a.png")
    assert stats._stats_split(disque.chemin("/ds/Train"))["annotes"] == 1


def test_stats_split_masque_a_plat_refuse(disque, monkeypatch):
    # La règle temporaire est désactivée
    monkeypatch.setattr(stats, "ACCEPTER_ANNOTATION_A_PLAT", False)
    disque.ajouter_fichier("/ds/Train/HSI/a.bil")
    disque.ajouter_fichier("/ds/Train/Annotation/a.png")
    assert stats._stats_split(disque.chemin("/ds/Train"))["annotes"] == 0


def test_stats_split_ancienne_structure_rgb(disque):
    # RGB contient encore un sous-dossier PNG : les photos sont ignorées,
    # donc le cube n'est pas compté comme incomplet à cause d'elles
    disque.ajouter_fichier("/ds/Train/HSI/a.bil")
    disque.ajouter_fichier("/ds/Train/HSI/a.bil.hdr")
    disque.ajouter_dossier("/ds/Train/RGB/PNG")
    resultat = stats._stats_split(disque.chemin("/ds/Train"))
    assert resultat["ancienne_structure"] is True
    assert resultat["incomplets"] == 0


def test_stats_split_sans_dossier_hsi(disque):
    disque.ajouter_dossier("/ds/Train")
    resultat = stats._stats_split(disque.chemin("/ds/Train"))
    assert resultat["cubes"] == 0


def test_stats_split_dossier_hsi_avec_suffixe(disque):
    disque.ajouter_fichier("/ds/Train/HSI-Hybercube/a.bil")
    assert stats._stats_split(disque.chemin("/ds/Train"))["cubes"] == 1


def test_stats_split_extensions_en_majuscules(disque):
    disque.ajouter_fichier("/ds/Train/HSI/a.BIL")
    assert stats._stats_split(disque.chemin("/ds/Train"))["cubes"] == 1


# --------------------------------------------------------- calculer_stats


def test_calculer_stats_dataset_introuvable(disque):
    assert stats.calculer_stats(disque.chemin("/nexiste/pas"))["etat"] == "Introuvable"


def test_calculer_stats_dossier_sans_split(disque):
    disque.ajouter_dossier("/ds/Autre")
    assert stats.calculer_stats(disque.chemin("/ds"))["etat"] == "Non conforme"


def test_calculer_stats_dataset_complet(disque, creer_dataset):
    creer_dataset("/ds", {"Train": ["a", "b"], "Test": ["c"], "Val": ["d"]})
    resultat = stats.calculer_stats(disque.chemin("/ds"))

    assert resultat["etat"] == "Complet"
    assert resultat["taches"] == []
    assert resultat["cubes_par_split"] == {"Train": 2, "Test": 1, "Val": 1}
    assert resultat["total_cubes"] == 4
    assert resultat["annotes"] == 4
    assert resultat["incomplets"] == 0


def test_calculer_stats_chemin_avec_slash_final(disque, creer_dataset):
    creer_dataset("/ds", {"Train": ["a"], "Test": ["b"], "Val": ["c"]})
    assert stats.calculer_stats(disque.chemin("/ds/"))["etat"] == "Complet"


def test_calculer_stats_noms_de_splits_en_minuscules(disque, creer_dataset):
    creer_dataset("/ds", {"train": ["a"], "test": ["b"], "val": ["c"]})
    resultat = stats.calculer_stats(disque.chemin("/ds"))
    assert resultat["etat"] == "Complet"
    # Les clés utilisent toujours les noms officiels des splits
    assert set(resultat["cubes_par_split"]) == {"Train", "Test", "Val"}


def test_calculer_stats_split_absent(disque, creer_dataset):
    creer_dataset("/ds", {"Train": ["a", "b"]})
    resultat = stats.calculer_stats(disque.chemin("/ds"))
    assert resultat["etat"] == "À compléter"
    assert resultat["taches"] == ["Split incomplet (dossier absent : Test, Val)"]


def test_calculer_stats_split_vide(disque, creer_dataset):
    creer_dataset("/ds", {"Train": ["a"], "Test": [], "Val": []})
    resultat = stats.calculer_stats(disque.chemin("/ds"))
    assert resultat["taches"] == ["Split incomplet (dossier vide : Test, Val)"]


def test_calculer_stats_plusieurs_taches_independantes(disque, creer_dataset):
    # Entêtes et masques manquants, en plus des splits absents
    creer_dataset("/ds", {"Train": ["a", "b"]}, hdr=False, annotes=False)
    resultat = stats.calculer_stats(disque.chemin("/ds"))

    assert resultat["etat"] == "À compléter"
    assert resultat["taches"] == [
        "Split incomplet (dossier absent : Test, Val)",
        "Masques d'annotation manquants : 2 (Train : 2)",
        "En-têtes .hdr manquants : 2 (Train : 2)",
    ]


def test_calculer_stats_ancienne_structure(disque, creer_dataset):
    creer_dataset("/ds", {"Train": ["a"], "Test": ["b"], "Val": ["c"]})
    disque.ajouter_dossier("/ds/Train/RGB/PNG")
    resultat = stats.calculer_stats(disque.chemin("/ds"))

    assert resultat["etat"] == "À compléter"
    assert resultat["taches"] == [
        "Ancienne structure RGB à migrer (retirer les dossiers PNG et TIFF)"
    ]


# ----------------------------------------------------------- lister_cubes


def test_lister_cubes_tries_par_ordre_alphabetique(disque, creer_dataset):
    creer_dataset("/ds", {"Train": ["c", "a", "b"]})
    assert stats.lister_cubes(disque.chemin("/ds"), "Train") == ["a", "b", "c"]


def test_lister_cubes_split_en_minuscules(disque, creer_dataset):
    creer_dataset("/ds", {"train": ["a"]})
    assert stats.lister_cubes(disque.chemin("/ds"), "Train") == ["a"]


def test_lister_cubes_split_absent(disque, creer_dataset):
    creer_dataset("/ds", {"Train": ["a"]})
    assert stats.lister_cubes(disque.chemin("/ds"), "Val") == []


def test_lister_cubes_dataset_introuvable(disque):
    assert stats.lister_cubes(disque.chemin("/nexiste/pas"), "Train") == []


# ------------------------------------------------------- tache_manquants


def test_tache_manquants_rien_ne_manque():
    assert stats.tache_manquants("Masques", {"Train": 0, "Test": 0}) is None


def test_tache_manquants_detail_par_split():
    texte = stats.tache_manquants("Masques", {"Train": 0, "Test": 1, "Val": 2})
    # Seuls les splits concernés apparaissent dans le détail
    assert texte == "Masques : 3 (Test : 1, Val : 2)"


def test_calculer_stats_images_rgb_manquantes(disque, creer_dataset):
    creer_dataset("/ds", {"Train": ["a"], "Test": ["b"], "Val": ["c"]}, rgb=False)
    resultat = stats.calculer_stats(disque.chemin("/ds"))

    assert resultat["etat"] == "À compléter"
    assert "Images RGB manquantes : 3 (Train : 1, Test : 1, Val : 1)" in resultat["taches"]

# -------------------------------------------------------- lire_dimensions

ENTETE_VALIDE = b"ENVI\nsamples = 640\nlines   = 480\nbands = 224\n"


def test_lire_dimensions_entete_valide(disque):
    disque.ajouter_fichier("/ds/Train/HSI/a.bil.hdr", ENTETE_VALIDE)
    assert stats.lire_dimensions(disque.chemin("/ds"), "Train", "a") == {
        "lignes": 480,
        "colonnes": 640,
        "bandes": 224,
    }


def test_lire_dimensions_cles_en_majuscules(disque):
    contenu = b"Samples = 10\nLINES = 20\nBands = 30\n"
    disque.ajouter_fichier("/ds/Train/HSI/a.bil.hdr", contenu)
    assert stats.lire_dimensions(disque.chemin("/ds"), "Train", "a") == {
        "lignes": 20,
        "colonnes": 10,
        "bandes": 30,
    }


def test_lire_dimensions_nom_de_fichier_en_majuscules(disque):
    disque.ajouter_fichier("/ds/Train/HSI/A.BIL.HDR", ENTETE_VALIDE)
    assert stats.lire_dimensions(disque.chemin("/ds"), "Train", "a")["bandes"] == 224


def test_lire_dimensions_cle_manquante(disque):
    disque.ajouter_fichier(
        "/ds/Train/HSI/a.bil.hdr", b"samples = 640\nlines = 480\n"
    )
    assert stats.lire_dimensions(disque.chemin("/ds"), "Train", "a") is None


def test_lire_dimensions_valeur_non_numerique(disque):
    contenu = b"samples = abc\nlines = 480\nbands = 224\n"
    disque.ajouter_fichier("/ds/Train/HSI/a.bil.hdr", contenu)
    assert stats.lire_dimensions(disque.chemin("/ds"), "Train", "a") is None


def test_lire_dimensions_entete_absent(disque):
    disque.ajouter_fichier("/ds/Train/HSI/a.bil")
    assert stats.lire_dimensions(disque.chemin("/ds"), "Train", "a") is None


def test_lire_dimensions_split_absent(disque):
    disque.ajouter_dossier("/ds/Train")
    assert stats.lire_dimensions(disque.chemin("/ds"), "Val", "a") is None


def test_lire_dimensions_dossier_hsi_absent(disque):
    disque.ajouter_dossier("/ds/Train")
    assert stats.lire_dimensions(disque.chemin("/ds"), "Train", "a") is None
