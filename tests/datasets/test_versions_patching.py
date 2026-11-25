"""
tests/datasets/test_versions_patching.py : tests de la lecture des versions
préparées dans modules/versions_patching.py.

Les dossiers de patches sont de vrais dossiers temporaires (fixture disque,
voir conftest.py). Les calculs purs (estimer_nb_patches) ne sont pas
concernés ici.
"""

import os
from datetime import datetime

from modules import versions_patching as vp
from modules.apprentissage import etape_patching

FORMAT_A = "w100_h100_sl50_sc50"
FORMAT_B = "w200_h200_sl100_sc100"


def ajouter_csv(disque, split, nom_format, fraction):
    """Crée le CSV d'une fraction (par exemple 100%) pour un split et un format."""
    dossier = f"/ds/hsi_data_patching/HSI/csv_for_dataloader/{split}/{nom_format}"
    disque.ajouter_fichier(f"{dossier}/{fraction}%_{split}_{nom_format}.csv")


# -------------------------------------------------------- date_modification


def test_date_modification_fichier_existant(disque):
    disque.ajouter_fichier("/ds/a.csv")
    os.utime(disque.chemin("/ds/a.csv"), (1_700_000_000, 1_700_000_000))
    assert vp.date_modification(disque.chemin("/ds/a.csv")) == 1_700_000_000


def test_date_modification_fichier_absent(disque):
    assert vp.date_modification(disque.chemin("/ds/absent.csv")) is None


# -------------------------------------------------------- lister_fractions


def test_lister_fractions_triees_par_ordre_croissant(disque):
    for fraction in (100, 10, 50):
        ajouter_csv(disque, "train", FORMAT_A, fraction)
    resultat = vp.lister_fractions(disque.chemin("/ds"), "Train", FORMAT_A)
    assert resultat == [10, 50, 100]


def test_lister_fractions_ignore_les_autres_fichiers(disque):
    ajouter_csv(disque, "train", FORMAT_A, 100)
    dossier = f"/ds/hsi_data_patching/HSI/csv_for_dataloader/train/{FORMAT_A}"
    disque.ajouter_fichier(f"{dossier}/notes.txt")
    # Fraction d'un autre split : ne correspond pas au motif de ce split
    disque.ajouter_fichier(f"{dossier}/20%_val_{FORMAT_A}.csv")
    assert vp.lister_fractions(disque.chemin("/ds"), "Train", FORMAT_A) == [100]


def test_lister_fractions_dossier_absent(disque):
    assert vp.lister_fractions(disque.chemin("/ds"), "Train", FORMAT_A) == []


# --------------------------------------------------------- lister_versions


def test_lister_versions_dataset_sans_patches(disque):
    disque.ajouter_dossier("/ds/Train")
    assert vp.lister_versions(disque.chemin("/ds")) == []


def test_lister_versions_dataset_introuvable(disque):
    # Plus d'exception : un dossier absent donne simplement une liste vide
    assert vp.lister_versions(disque.chemin("/nexiste/pas")) == []


def test_lister_versions_un_format_avec_un_split_pret(disque):
    ajouter_csv(disque, "train", FORMAT_A, 10)
    ajouter_csv(disque, "train", FORMAT_A, 100)

    versions = vp.lister_versions(disque.chemin("/ds"))

    assert len(versions) == 1
    assert versions[0]["nom"] == FORMAT_A
    assert versions[0]["splits_prets"] == ["Train"]
    assert versions[0]["fractions"] == {"Train": [10, 100]}


def test_lister_versions_plusieurs_splits_dans_l_ordre_officiel(disque):
    for split in ("val", "train"):
        ajouter_csv(disque, split, FORMAT_A, 100)
    versions = vp.lister_versions(disque.chemin("/ds"))
    assert versions[0]["splits_prets"] == ["Train", "Val"]


def test_lister_versions_sans_csv_a_100_pourcent_le_format_n_est_pas_liste(disque):
    # Patching interrompu : seules des fractions partielles existent
    ajouter_csv(disque, "train", FORMAT_A, 10)
    ajouter_csv(disque, "train", FORMAT_A, 50)
    assert vp.lister_versions(disque.chemin("/ds")) == []


def test_lister_versions_ignore_les_dossiers_qui_ne_sont_pas_des_formats(disque):
    ajouter_csv(disque, "train", FORMAT_A, 100)
    ajouter_csv(disque, "train", "brouillon", 100)
    noms = [v["nom"] for v in vp.lister_versions(disque.chemin("/ds"))]
    assert noms == [FORMAT_A]


def test_lister_versions_triees_par_nom(disque):
    ajouter_csv(disque, "train", FORMAT_B, 100)
    ajouter_csv(disque, "train", FORMAT_A, 100)
    noms = [v["nom"] for v in vp.lister_versions(disque.chemin("/ds"))]
    assert noms == [FORMAT_A, FORMAT_B]


def test_lister_versions_date_de_creation_du_csv_le_plus_recent(disque):
    ajouter_csv(disque, "train", FORMAT_A, 100)
    ajouter_csv(disque, "val", FORMAT_A, 100)
    base = "/ds/hsi_data_patching/HSI/csv_for_dataloader"
    os.utime(
        disque.chemin(f"{base}/train/{FORMAT_A}/100%_train_{FORMAT_A}.csv"),
        (1_700_000_000, 1_700_000_000),
    )
    os.utime(
        disque.chemin(f"{base}/val/{FORMAT_A}/100%_val_{FORMAT_A}.csv"),
        (1_700_100_000, 1_700_100_000),
    )

    versions = vp.lister_versions(disque.chemin("/ds"))

    attendu = datetime.fromtimestamp(1_700_100_000).isoformat(timespec="seconds")
    assert versions[0]["date_creation"] == attendu


def test_lire_versions_renvoie_une_liste_vide_sans_patches(disque):
    disque.ajouter_dossier("/ds/Train")
    assert etape_patching.lire_versions(disque.chemin("/ds")) == []


# -------------------------------------------------------- chemin_patching


def test_chemin_patching_avec_slash_final():
    assert vp.chemin_patching("/ds/") == "/ds/hsi_data_patching"


def test_chemin_marqueur_utilise_les_noms_de_splits_en_minuscules():
    chemin = vp.chemin_marqueur("/ds", "Train", FORMAT_A)
    assert chemin == (
        f"/ds/hsi_data_patching/HSI/csv_for_dataloader/train/{FORMAT_A}/"
        f"100%_train_{FORMAT_A}.csv"
    )
