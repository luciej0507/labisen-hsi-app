"""
tests/datasets/test_exploration_dataset.py : tests de
modules/datasets/exploration_dataset.py

Le serveur est un faux serveur SFTP en mémoire (voir conftest.py) et la base
est une fausse collection mongomock (fixture users).
"""

from modules.datasets import exploration_dataset as expl


# ------------------------------------------------------ list_folder_contents


def test_list_folder_contents_dossiers_d_abord_puis_tri_alphabetique(brancher_sftp):
    brancher_sftp.ajouter_fichier("/data/z.txt")
    brancher_sftp.ajouter_fichier("/data/a.txt")
    brancher_sftp.ajouter_dossier("/data/beta")
    brancher_sftp.ajouter_dossier("/data/alpha")

    elements = expl.list_folder_contents("/data")

    assert [e["nom"] for e in elements] == ["alpha", "beta", "a.txt", "z.txt"]
    assert [e["est_dossier"] for e in elements] == [True, True, False, False]


def test_list_folder_contents_renvoie_les_chemins_complets(brancher_sftp):
    brancher_sftp.ajouter_dossier("/data/alpha")
    elements = expl.list_folder_contents("/data")
    assert elements == [
        {"nom": "alpha", "chemin": "/data/alpha", "est_dossier": True}
    ]


def test_list_folder_contents_chemin_avec_slash_final(brancher_sftp):
    brancher_sftp.ajouter_dossier("/data/alpha")
    elements = expl.list_folder_contents("/data/")
    assert elements[0]["chemin"] == "/data/alpha"


def test_list_folder_contents_un_seul_niveau(brancher_sftp):
    brancher_sftp.ajouter_fichier("/data/alpha/profond/fichier.txt")
    elements = expl.list_folder_contents("/data")
    # Seul le contenu direct est listé, pas les sous-dossiers
    assert [e["nom"] for e in elements] == ["alpha"]


def test_list_folder_contents_dossier_vide(brancher_sftp):
    brancher_sftp.ajouter_dossier("/data/vide")
    assert expl.list_folder_contents("/data/vide") == []


def test_list_folder_contents_dossier_inaccessible(brancher_sftp):
    assert expl.list_folder_contents("/nexiste/pas") == []


def test_list_folder_contents_serveur_injoignable(serveur_injoignable):
    assert expl.list_folder_contents("/data") == []


# ------------------------------------------------ mettre_a_jour_selection


def test_selection_ajout():
    assert expl.mettre_a_jour_selection(set(), "/data/a", True) == {"/data/a"}


def test_selection_retrait():
    selection = {"/data/a", "/data/b"}
    assert expl.mettre_a_jour_selection(selection, "/data/a", False) == {"/data/b"}


def test_selection_retrait_d_un_chemin_absent():
    # Aucune erreur si le chemin n'était pas dans la sélection
    assert expl.mettre_a_jour_selection({"/data/a"}, "/data/b", False) == {"/data/a"}


def test_selection_ajout_d_un_chemin_deja_present():
    assert expl.mettre_a_jour_selection({"/data/a"}, "/data/a", True) == {"/data/a"}


def test_selection_d_origine_non_modifiee():
    origine = {"/data/a"}
    nouvelle = expl.mettre_a_jour_selection(origine, "/data/b", True)
    assert origine == {"/data/a"}
    assert nouvelle is not origine


# ------------------------------------------------------------ chemin_relatif


def test_chemin_relatif_retire_la_racine():
    assert expl.chemin_relatif("/data", "/data/alice/ds1") == "alice/ds1"


def test_chemin_relatif_racine_avec_slash_final():
    assert expl.chemin_relatif("/data/", "/data/alice/ds1") == "alice/ds1"


def test_chemin_relatif_hors_racine_inchange():
    assert expl.chemin_relatif("/data", "/autre/ds1") == "/autre/ds1"


def test_chemin_relatif_prefixe_partiel_inchange():
    # "/database" commence par "/data" mais n'est pas situé sous "/data/"
    assert expl.chemin_relatif("/data", "/database/ds1") == "/database/ds1"


def test_chemin_relatif_chemin_egal_a_la_racine():
    assert expl.chemin_relatif("/data", "/data") == "/data"


# --------------------------------------------------- get_datasets_autorises


def test_datasets_autorises_utilisateur_inexistant(users):
    assert expl.get_datasets_autorises(users, "fantome") == []


def test_datasets_autorises_sans_acces(users, creer_compte):
    creer_compte("alice")
    assert expl.get_datasets_autorises(users, "alice") == []


def test_datasets_autorises_avec_acces(users, creer_compte):
    creer_compte("alice")
    users.update_one(
        {"username": "alice"},
        {"$set": {"datasets_access": ["/data/alice/ds1", "/data/alice/ds2"]}},
    )
    assert expl.get_datasets_autorises(users, "alice") == [
        "/data/alice/ds1",
        "/data/alice/ds2",
    ]


def test_datasets_autorises_champ_absent(users):
    # Ancien compte créé sans le champ datasets_access
    users.insert_one({"username": "bob"})
    assert expl.get_datasets_autorises(users, "bob") == []


def test_datasets_autorises_champ_vide_ou_none(users):
    users.insert_one({"username": "bob", "datasets_access": None})
    assert expl.get_datasets_autorises(users, "bob") == []


def test_datasets_autorises_lecture_a_jour_a_chaque_appel(users, creer_compte):
    creer_compte("alice")
    assert expl.get_datasets_autorises(users, "alice") == []

    # L'admin donne un accès : il est visible immédiatement
    users.update_one(
        {"username": "alice"}, {"$set": {"datasets_access": ["/data/ds1"]}}
    )
    assert expl.get_datasets_autorises(users, "alice") == ["/data/ds1"]