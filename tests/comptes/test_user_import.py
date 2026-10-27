"""
tests/comptes/test_user_import.py : tests de modules/comptes/user_import.py

Ce module ne contient que des fonctions pures (pas de Streamlit, pas de
MongoDB) : les tests sont rapides et n'ont besoin d'aucun faux objet. Seul
le test de bout en bout, à la fin, utilise la fausse base du conftest.

Les messages d'erreur sont vérifiés avec un mot-clé plutôt qu'avec le texte
exact, comme dans test_users.py.
"""

import pandas as pd
import pytest

from modules.comptes import user_import as ui
from modules.comptes.users import create_users_from_rows

# Un CSV valide de deux lignes (la seconde n'a pas d'email)
CSV_VALIDE = (
    "nom;prenom;email;username\n"
    "Dupont;Marie;marie@exemple.fr;mdupont\n"
    "Martin;Paul;;pmartin\n"
)


def tableau(*lignes) -> pd.DataFrame:
    """
    Construit un DataFrame comme parse_csv le ferait, à partir de tuples
    (nom, prenom, email, username). L'index commence à 1.
    """
    df = pd.DataFrame(list(lignes), columns=ui.CSV_COLUMNS, dtype=str)
    df.index = range(1, len(df) + 1)
    return df


# ---------------------------------------------------------------------------
# _normalize_column_name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "nom_colonne, attendu",
    [
        ("Prénom ", "prenom"),
        ("NOM", "nom"),
        ("  Username", "username"),
        ("Émail", "email"),
        (123, "123"),
    ],
)
def test_normalize_column_name(nom_colonne, attendu):
    """Les en-têtes sont mis en minuscules, sans accent ni espace autour."""
    assert ui._normalize_column_name(nom_colonne) == attendu


# ---------------------------------------------------------------------------
# _decode
# ---------------------------------------------------------------------------

def test_decode_utf8():
    """Un texte UTF-8 est décodé tel quel."""
    assert ui._decode("Prénom".encode("utf-8")) == "Prénom"


def test_decode_utf8_avec_bom():
    """Le BOM ajouté par Excel en début de fichier est retiré."""
    assert ui._decode(b"\xef\xbb\xbfnom") == "nom"


def test_decode_cp1252():
    """Un fichier Excel français (cp1252) est décodé correctement."""
    assert ui._decode("Prénom".encode("cp1252")) == "Prénom"


# ---------------------------------------------------------------------------
# clean_dataframe
# ---------------------------------------------------------------------------

def test_clean_dataframe_garde_les_colonnes_connues_dans_l_ordre():
    """Les colonnes inconnues sont retirées, les colonnes absentes remplies de vide."""
    df = pd.DataFrame(
        {"username": ["a"], "inconnue": ["x"], "nom": ["N"], "prenom": ["P"]}
    )

    propre = ui.clean_dataframe(df)

    assert list(propre.columns) == ui.CSV_COLUMNS
    assert propre.iloc[0]["email"] == ""


def test_clean_dataframe_retire_les_espaces_et_les_valeurs_nulles():
    """Les espaces autour des valeurs sont retirés, les valeurs nulles deviennent vides."""
    df = pd.DataFrame(
        {
            "nom": ["  Dupont "],
            "prenom": [None],
            "email": [None],
            "username": [" mdupont"],
        }
    )

    propre = ui.clean_dataframe(df)

    assert propre.iloc[0].to_dict() == {
        "nom": "Dupont",
        "prenom": "",
        "email": "",
        "username": "mdupont",
    }


def test_clean_dataframe_supprime_les_lignes_vides_et_garde_l_index():
    """Une ligne entièrement vide disparaît, l'index d'origine est conservé."""
    df = pd.DataFrame(
        {
            "nom": ["Dupont", "  ", "Martin"],
            "prenom": ["Marie", "", "Paul"],
            "email": ["", "", ""],
            "username": ["mdupont", "", "pmartin"],
        }
    )

    propre = ui.clean_dataframe(df)

    assert list(propre.index) == [0, 2]


# ---------------------------------------------------------------------------
# parse_csv : fichiers valides
# ---------------------------------------------------------------------------

def test_parse_csv_valide():
    """Un CSV correct donne un tableau indexé à partir de 1."""
    df = ui.parse_csv(CSV_VALIDE.encode("utf-8"))

    assert list(df.columns) == ui.CSV_COLUMNS
    assert list(df.index) == [1, 2]
    assert df.loc[1, "username"] == "mdupont"
    assert df.loc[1, "email"] == "marie@exemple.fr"
    assert df.loc[2, "email"] == ""


def test_parse_csv_separateur_virgule():
    """Le séparateur "," est reconnu comme le ";"."""
    texte = CSV_VALIDE.replace(";", ",")

    df = ui.parse_csv(texte.encode("utf-8"))

    assert list(df.index) == [1, 2]
    assert df.loc[2, "username"] == "pmartin"


def test_parse_csv_en_tetes_avec_accents_et_majuscules():
    """Les en-têtes "Nom;Prénom;Email;Username" sont reconnus."""
    texte = "Nom;Prénom;Email;Username\nDupont;Marie;;mdupont\n"

    df = ui.parse_csv(texte.encode("utf-8"))

    assert df.loc[1, "prenom"] == "Marie"


def test_parse_csv_utf8_avec_bom():
    """Un fichier UTF-8 avec BOM (export Excel) est lu correctement."""
    df = ui.parse_csv(("﻿" + CSV_VALIDE).encode("utf-8"))

    assert list(df.columns) == ui.CSV_COLUMNS
    assert df.loc[1, "nom"] == "Dupont"


def test_parse_csv_cp1252():
    """Un fichier Excel français (cp1252) garde ses accents."""
    texte = "nom;prenom;email;username\nDupont;Hélène;;hdupont\n"

    df = ui.parse_csv(texte.encode("cp1252"))

    assert df.loc[1, "prenom"] == "Hélène"


def test_parse_csv_colonne_email_optionnelle():
    """Sans colonne email, la colonne est créée vide."""
    texte = "nom;prenom;username\nDupont;Marie;mdupont\n"

    df = ui.parse_csv(texte.encode("utf-8"))

    assert df.loc[1, "email"] == ""


def test_parse_csv_colonnes_inconnues_ignorees():
    """Une colonne en plus dans le fichier est ignorée."""
    texte = "nom;prenom;username;telephone\nDupont;Marie;mdupont;0102030405\n"

    df = ui.parse_csv(texte.encode("utf-8"))

    assert list(df.columns) == ui.CSV_COLUMNS
    assert df.loc[1, "username"] == "mdupont"


def test_parse_csv_colonne_en_double_garde_la_premiere():
    """Si une colonne apparaît deux fois, la première est conservée."""
    texte = "nom;nom;prenom;username\nPremier;Second;Marie;mdupont\n"

    df = ui.parse_csv(texte.encode("utf-8"))

    assert df.loc[1, "nom"] == "Premier"


def test_parse_csv_cellule_entre_guillemets_avec_separateur():
    """Une cellule entre guillemets peut contenir le séparateur."""
    texte = 'nom;prenom;email;username\n"Dupont;Jr";Marie;;mdupont\n'

    df = ui.parse_csv(texte.encode("utf-8"))

    assert df.loc[1, "nom"] == "Dupont;Jr"


def test_parse_csv_ligne_courte_completee():
    """Une ligne avec moins de valeurs que l'en-tête est complétée avec du vide."""
    texte = "nom;prenom;email;username\nDupont;Marie\n"

    df = ui.parse_csv(texte.encode("utf-8"))

    assert df.loc[1, "username"] == ""


def test_parse_csv_ligne_longue_avec_valeurs_en_trop_vides():
    """Des séparateurs en trop sans valeur (fréquent avec Excel) sont tolérés."""
    texte = "nom;prenom;email;username\nDupont;Marie;;mdupont;;\n"

    df = ui.parse_csv(texte.encode("utf-8"))

    assert df.loc[1, "username"] == "mdupont"


def test_parse_csv_lignes_vides_ignorees_et_index_continu():
    """Les lignes vides (ou faites uniquement de séparateurs) n'ont pas de numéro."""
    texte = (
        "nom;prenom;email;username\n"
        "Dupont;Marie;;mdupont\n"
        "\n"
        ";;;\n"
        "Martin;Paul;;pmartin\n"
    )

    df = ui.parse_csv(texte.encode("utf-8"))

    assert list(df.index) == [1, 2]
    assert df.loc[2, "username"] == "pmartin"


# ---------------------------------------------------------------------------
# parse_csv : fichiers inutilisables
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("contenu", [b"", b"   \n  "])
def test_parse_csv_fichier_vide(contenu):
    """Un fichier vide est refusé avec un message lisible."""
    with pytest.raises(ValueError, match="vide"):
        ui.parse_csv(contenu)


def test_parse_csv_colonne_obligatoire_manquante():
    """Les colonnes obligatoires manquantes sont nommées dans le message."""
    with pytest.raises(ValueError, match="manquantes : username"):
        ui.parse_csv(b"nom;prenom\nDupont;Marie\n")


def test_parse_csv_plusieurs_colonnes_manquantes():
    """Toutes les colonnes manquantes sont listées."""
    with pytest.raises(ValueError, match="manquantes : nom, username"):
        ui.parse_csv(b"prenom\nMarie\n")


@pytest.mark.parametrize(
    "texte",
    [
        "nom;prenom;email;username\n",
        "nom;prenom;email;username\n;;;\n  ;  ;;\n",
    ],
)
def test_parse_csv_aucune_ligne_exploitable(texte):
    """Un fichier avec seulement l'en-tête (ou des lignes vides) est refusé."""
    with pytest.raises(ValueError, match="aucune ligne"):
        ui.parse_csv(texte.encode("utf-8"))


def test_parse_csv_ligne_trop_longue():
    """Une ligne avec des valeurs en trop est signalée, avec son numéro."""
    texte = "nom;prenom;email;username\nDupont;Marie;m@exemple.fr;mdupont;en trop\n"

    with pytest.raises(ValueError, match="Ligne 2") as erreur:
        ui.parse_csv(texte.encode("utf-8"))

    assert "trop de valeurs" in str(erreur.value)


# ---------------------------------------------------------------------------
# classify_rows
# ---------------------------------------------------------------------------

def test_classify_rows_nouveau_compte():
    """Un username inconnu donne un nouveau compte à créer."""
    df = tableau(("Dupont", "Marie", "marie@exemple.fr", "mdupont"))

    ligne = ui.classify_rows(df, [])[0]

    assert ligne["ligne"] == 1
    assert ligne["statut"] == ui.STATUS_CREATE
    assert ligne["motif"] == "nouveau compte"
    assert ligne["action"] == ui.ACTION_CREATE
    assert ligne["email"] == "marie@exemple.fr"


def test_classify_rows_email_vide_devient_none():
    """Un email vide est renvoyé comme None (comme il sera stocké en base)."""
    df = tableau(("Dupont", "Marie", "", "mdupont"))

    assert ui.classify_rows(df, [])[0]["email"] is None


def test_classify_rows_compte_existant():
    """Un username déjà en base donne une ligne "existant", ignorée par défaut."""
    df = tableau(("Dupont", "Marie", "marie@exemple.fr", "mdupont"))
    existants = [{"username": "mdupont", "email": "marie@exemple.fr"}]

    ligne = ui.classify_rows(df, existants)[0]

    assert ligne["statut"] == ui.STATUS_EXISTING
    assert "existant" in ligne["motif"]
    assert ligne["action"] == ui.ACTION_IGNORE


def test_classify_rows_username_sensible_a_la_casse():
    """"MDupont" n'est pas "mdupont" : comme à la connexion, la casse compte."""
    df = tableau(("Dupont", "Marie", "", "MDupont"))
    existants = [{"username": "mdupont", "email": None}]

    assert ui.classify_rows(df, existants)[0]["statut"] == ui.STATUS_CREATE


def test_classify_rows_existants_sans_email():
    """Des comptes en base sans email ne posent aucun problème."""
    df = tableau(("Dupont", "Marie", "marie@exemple.fr", "mdupont"))
    existants = [{"username": "autre", "email": None}, {"username": "sans_champ"}]

    assert ui.classify_rows(df, existants)[0]["statut"] == ui.STATUS_CREATE


def test_classify_rows_doublon_dans_le_fichier():
    """La première occurrence est conservée, les suivantes sont des doublons."""
    df = tableau(
        ("Dupont", "Marie", "", "mdupont"),
        ("Dupont", "Marie", "", "mdupont"),
    )

    lignes = ui.classify_rows(df, [])

    assert lignes[0]["statut"] == ui.STATUS_CREATE
    assert lignes[1]["statut"] == ui.STATUS_DUPLICATE
    assert lignes[1]["action"] == ui.ACTION_IGNORE


@pytest.mark.parametrize(
    "ligne, motif",
    [
        (("", "Marie", "", "mdupont"), "nom manquant"),
        (("Dupont", "", "", "mdupont"), "prénom manquant"),
        (("Dupont", "Marie", "", ""), "identifiant manquant"),
    ],
)
def test_classify_rows_champ_obligatoire_manquant(ligne, motif):
    """Un champ obligatoire vide rend la ligne invalide, à corriger."""
    resultat = ui.classify_rows(tableau(ligne), [])[0]

    assert resultat["statut"] == ui.STATUS_INVALID
    assert resultat["motif"] == motif
    assert resultat["action"] == ui.ACTION_FIX


def test_classify_rows_plusieurs_problemes_cumules():
    """Tous les problèmes d'une ligne sont listés dans le motif."""
    df = tableau(("", "", "marie@exemple.fr", ""))

    ligne = ui.classify_rows(df, [])[0]

    assert ligne["motif"] == "nom manquant ; prénom manquant ; identifiant manquant"


@pytest.mark.parametrize(
    "email",
    ["pas-un-email", "a@b", "a b@exemple.fr", "a@exemple.fr;b@exemple.fr"],
)
def test_classify_rows_email_invalide(email):
    """Un email mal formé rend la ligne invalide."""
    df = tableau(("Dupont", "Marie", email, "mdupont"))

    ligne = ui.classify_rows(df, [])[0]

    assert ligne["statut"] == ui.STATUS_INVALID
    assert "email invalide" in ligne["motif"]


def test_classify_rows_ligne_vide():
    """Une ligne entièrement vide est ignorée, sans erreur."""
    ligne = ui.classify_rows(tableau(("", "", "", "")), [])[0]

    assert ligne["statut"] == ui.STATUS_EMPTY
    assert ligne["motif"] == "ligne vide"
    assert ligne["action"] == ui.ACTION_IGNORE


def test_classify_rows_email_pris_par_un_autre_compte_en_base():
    """Un email déjà utilisé par un autre compte n'est jamais écrasé."""
    df = tableau(("Dupont", "Marie", "marie@exemple.fr", "mdupont"))
    existants = [{"username": "autre", "email": "marie@exemple.fr"}]

    ligne = ui.classify_rows(df, existants)[0]

    assert ligne["statut"] == ui.STATUS_INVALID
    assert "déjà utilisé" in ligne["motif"]


def test_classify_rows_email_compare_sans_tenir_compte_de_la_casse():
    """"MARIE@EXEMPLE.FR" et "marie@exemple.fr" sont le même email."""
    df = tableau(("Dupont", "Marie", "MARIE@EXEMPLE.FR", "mdupont"))
    existants = [{"username": "autre", "email": "marie@exemple.fr"}]

    assert ui.classify_rows(df, existants)[0]["statut"] == ui.STATUS_INVALID


def test_classify_rows_email_en_doublon_dans_le_fichier():
    """Le même email pour deux usernames différents est une erreur à corriger."""
    df = tableau(
        ("Dupont", "Marie", "marie@exemple.fr", "mdupont"),
        ("Martin", "Paul", "marie@exemple.fr", "pmartin"),
    )

    lignes = ui.classify_rows(df, [])

    assert lignes[0]["statut"] == ui.STATUS_CREATE
    assert lignes[1]["statut"] == ui.STATUS_INVALID
    assert "doublon dans le fichier" in lignes[1]["motif"]


def test_classify_rows_ligne_rejetee_ne_bloque_pas_les_suivantes():
    """Une ligne invalide n'est pas retenue : le même username plus bas reste valable."""
    df = tableau(
        ("Dupont", "Marie", "mauvais", "mdupont"),
        ("Dupont", "Marie", "", "mdupont"),
    )

    lignes = ui.classify_rows(df, [])

    assert [ligne["statut"] for ligne in lignes] == [ui.STATUS_INVALID, ui.STATUS_CREATE]


def test_classify_rows_numeros_de_ligne_pris_dans_l_index():
    """Le numéro de ligne affiché est celui de l'index du tableau."""
    df = tableau(
        ("Dupont", "Marie", "", "mdupont"),
        ("Martin", "Paul", "", "pmartin"),
    )
    df.index = [3, 7]

    lignes = ui.classify_rows(df, [])

    assert [ligne["ligne"] for ligne in lignes] == [3, 7]


# ---------------------------------------------------------------------------
# resolve_action
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "statut, choix, attendu",
    [
        (ui.STATUS_CREATE, None, ui.ACTION_CREATE),
        (ui.STATUS_CREATE, ui.ACTION_IGNORE, ui.ACTION_IGNORE),
        (ui.STATUS_EXISTING, None, ui.ACTION_IGNORE),
        (ui.STATUS_EXISTING, ui.ACTION_UPDATE, ui.ACTION_UPDATE),
        # Choix non autorisé pour ce statut : l'action par défaut s'applique
        (ui.STATUS_EXISTING, ui.ACTION_CREATE, ui.ACTION_IGNORE),
        (ui.STATUS_DUPLICATE, ui.ACTION_CREATE, ui.ACTION_IGNORE),
        (ui.STATUS_INVALID, ui.ACTION_CREATE, ui.ACTION_FIX),
        (ui.STATUS_EMPTY, ui.ACTION_UPDATE, ui.ACTION_IGNORE),
    ],
)
def test_resolve_action(statut, choix, attendu):
    """Le choix de l'admin est appliqué seulement s'il est autorisé pour le statut."""
    assert ui.resolve_action(statut, choix) == attendu


# ---------------------------------------------------------------------------
# apply_actions
# ---------------------------------------------------------------------------

def lignes_de_tous_les_statuts() -> list:
    """Cinq lignes, une par statut : créer, existant, doublon, invalide, vide."""
    df = tableau(
        ("Dupont", "Marie", "", "mdupont"),  # ligne 1 : à créer
        ("Martin", "Paul", "", "pmartin"),   # ligne 2 : existant
        ("Dupont", "Marie", "", "mdupont"),  # ligne 3 : doublon de la ligne 1
        ("", "Paul", "", "x"),               # ligne 4 : nom manquant
        ("", "", "", ""),                    # ligne 5 : vide
    )
    return ui.classify_rows(df, [{"username": "pmartin", "email": None}])


def numeros(lignes) -> list:
    """Numéros de ligne d'une liste de lignes."""
    return [ligne["ligne"] for ligne in lignes]


def test_apply_actions_actions_par_defaut():
    """Sans choix de l'admin, chaque ligne reçoit son action par défaut."""
    a_creer, a_maj, ignorees, a_corriger = ui.apply_actions(
        lignes_de_tous_les_statuts(), {}
    )

    assert numeros(a_creer) == [1]
    assert numeros(a_maj) == []
    assert numeros(ignorees) == [2, 3]
    assert numeros(a_corriger) == [4]


def test_apply_actions_choix_de_l_admin():
    """Les choix autorisés sont appliqués, les autres sont remplacés par le défaut."""
    choix = {
        1: ui.ACTION_IGNORE,
        2: ui.ACTION_UPDATE,
        3: ui.ACTION_CREATE,  # non autorisé pour un doublon
    }

    a_creer, a_maj, ignorees, a_corriger = ui.apply_actions(
        lignes_de_tous_les_statuts(), choix
    )

    assert numeros(a_creer) == []
    assert numeros(a_maj) == [2]
    assert numeros(ignorees) == [1, 3]
    assert numeros(a_corriger) == [4]


def test_apply_actions_ecarte_les_lignes_vides():
    """Une ligne entièrement vide n'apparaît dans aucune liste."""
    listes = ui.apply_actions(lignes_de_tous_les_statuts(), {})

    assert all(5 not in numeros(liste) for liste in listes)


# ---------------------------------------------------------------------------
# build_template_csv
# ---------------------------------------------------------------------------

def test_build_template_csv_format_excel():
    """Le modèle a un BOM UTF-8, le séparateur ";" et les bonnes colonnes."""
    brut = ui.build_template_csv()

    assert brut.startswith(b"\xef\xbb\xbf")
    en_tete = brut.decode("utf-8-sig").splitlines()[0]
    assert en_tete == "nom;prenom;email;username"


def test_build_template_csv_est_relisible():
    """Le modèle téléchargé peut être réimporté tel quel, sans erreur."""
    df = ui.parse_csv(ui.build_template_csv())

    assert len(df) == 1
    assert ui.classify_rows(df, [])[0]["statut"] == ui.STATUS_CREATE


# ---------------------------------------------------------------------------
# Import complet, de bout en bout
# ---------------------------------------------------------------------------

def test_import_complet(users, creer_compte):
    """CSV, analyse, choix par défaut, puis création en base."""
    creer_compte("pmartin")
    contenu = (
        "nom;prenom;email;username\n"
        "Dupont;Marie;marie@exemple.fr;mdupont\n"
        "Martin;Paul;;pmartin\n"
        "Durand;;;\n"
    ).encode("utf-8")

    df = ui.parse_csv(contenu)
    existants = list(users.find({}, {"username": 1, "email": 1}))
    lignes = ui.classify_rows(df, existants)
    a_creer, a_maj, ignorees, a_corriger = ui.apply_actions(lignes, {})
    crees, echecs = create_users_from_rows(users, a_creer)

    assert [c["username"] for c in crees] == ["mdupont"]
    assert echecs == []
    # Le compte existant est ignoré, la ligne incomplète est à corriger
    assert numeros(ignorees) == [2]
    assert numeros(a_corriger) == [3]
    assert users.count_documents({}) == 2