"""
tests/test_users.py : tests de modules/users.py.

Les messages d'erreur sont vérifiés avec un mot-clé (assert "mot" in message)
plutôt qu'avec le texte exact : les tests ne cassent pas si on corrige
les accents ou la formulation.
"""

from datetime import datetime

import bcrypt
import pytest
from bson import ObjectId
from pymongo.errors import DuplicateKeyError, PyMongoError

from modules.users import (
    create_user,
    delete_blocked_reason,
    delete_user,
    ensure_username_index,
    format_date,
    hash_password,
    update_user,
    validate_new_user,
    validate_user_update,
)


# ---------------------------------------------------------------------------
# hash_password
# ---------------------------------------------------------------------------

def test_hash_password_est_verifiable_avec_bcrypt():
    """Le hash produit correspond bien au mot de passe d'origine."""
    hashed = hash_password("secret123")

    assert hashed != "secret123"
    assert bcrypt.checkpw(b"secret123", hashed.encode("utf-8"))
    assert not bcrypt.checkpw(b"autre", hashed.encode("utf-8"))


def test_hash_password_est_different_a_chaque_appel():
    """Le sel est aléatoire : deux hash du même mot de passe diffèrent."""
    assert hash_password("secret123") != hash_password("secret123")


# ---------------------------------------------------------------------------
# format_date
# ---------------------------------------------------------------------------

def test_format_date():
    """Une date est formatée en JJ/MM/AAAA, le vide donne une chaîne vide."""
    assert format_date(datetime(2026, 9, 24)) == "24/09/2026"
    assert format_date(None) == ""
    assert format_date("texte") == "texte"


# ---------------------------------------------------------------------------
# ensure_username_index
# ---------------------------------------------------------------------------

def test_ensure_username_index_reussit(users):
    """Sur une base saine, la fonction renvoie True."""
    assert ensure_username_index(users) is True


def test_ensure_username_index_echec_renvoie_false():
    """Si MongoDB refuse de créer l'index, la fonction renvoie False."""

    class CollectionEnPanne:
        """Fausse collection dont create_index échoue toujours."""

        def create_index(self, *args, **kwargs):
            raise PyMongoError("échec simulé")

    assert ensure_username_index(CollectionEnPanne()) is False


# ---------------------------------------------------------------------------
# validate_new_user
# ---------------------------------------------------------------------------

def champs_valides(**surcharges) -> dict:
    """Champs d'un formulaire d'ajout valide, modifiables au cas par cas."""
    champs = {
        "nom": "Dupont",
        "prenom": "Marie",
        "username": "mdupont",
        "password": "secret123",
        "password_confirm": "secret123",
    }
    champs.update(surcharges)
    return champs


def test_validate_new_user_valide(users):
    """Un formulaire correct ne renvoie aucune erreur."""
    assert validate_new_user(**champs_valides(), users=users) is None


# parametrize : le même test est exécuté une fois par ligne du tableau
@pytest.mark.parametrize(
    "champ, mot_cle",
    [
        ("nom", "Le nom ne"),
        ("prenom", "Le pr"),
        ("username", "utilisateur"),
        ("password", "mot de passe"),
    ],
)
def test_validate_new_user_champ_vide(users, champ, mot_cle):
    """Chaque champ obligatoire vide est refusé (espaces seuls compris, sauf pour le mot de passe)."""
    # Le mot de passe n'est pas nettoyé avec strip() : des espaces y sont valides
    valeurs_vides = ("",) if champ == "password" else ("", "   ")

    for valeur_vide in valeurs_vides:
        # password_confirm est aligné pour que seul le champ testé pose problème
        surcharges = {champ: valeur_vide}
        if champ == "password":
            surcharges["password_confirm"] = valeur_vide
        message = validate_new_user(**champs_valides(**surcharges), users=users)

        assert message is not None
        assert "vide" in message
        assert mot_cle in message


def test_validate_new_user_mots_de_passe_differents(users):
    """Deux mots de passe différents sont refusés."""
    message = validate_new_user(
        **champs_valides(password_confirm="autre"), users=users
    )

    assert message is not None
    assert "correspondent" in message


def test_validate_new_user_username_deja_pris(users, creer_compte):
    """Un username déjà en base est refusé, même avec des espaces autour."""
    creer_compte("mdupont")

    for username in ("mdupont", "  mdupont  "):
        message = validate_new_user(**champs_valides(username=username), users=users)

        assert message is not None
        assert "existe" in message


# ---------------------------------------------------------------------------
# create_user
# ---------------------------------------------------------------------------

def test_create_user_insere_le_compte(users):
    """Le compte est inséré avec un mot de passe haché, jamais en clair."""
    resume = create_user(
        users,
        nom="  Dupont ",
        prenom="Marie",
        email="marie@exemple.fr",
        username=" mdupont ",
        password="secret123",
        role="user",
        datasets_access=["dataset_a"],
    )

    en_base = users.find_one({"username": "mdupont"})

    # Les espaces sont retirés
    assert en_base["nom"] == "Dupont"
    assert en_base["email"] == "marie@exemple.fr"
    assert en_base["datasets_access"] == ["dataset_a"]
    assert isinstance(en_base["created_at"], datetime)
    # Le mot de passe est haché et vérifiable
    assert en_base["password_hash"] != "secret123"
    assert bcrypt.checkpw(b"secret123", en_base["password_hash"].encode("utf-8"))
    # Le récapitulatif ne contient pas le hash
    assert "password_hash" not in resume
    assert resume["username"] == "mdupont"


def test_create_user_email_vide_devient_none(users):
    """Un email vide est stocké comme None."""
    create_user(users, "Dupont", "Marie", "", "mdupont", "secret123", "user", [])

    assert users.find_one({"username": "mdupont"})["email"] is None


def test_create_user_doublon_leve_une_erreur(users, creer_compte):
    """L'index unique de la base refuse un username déjà présent."""
    creer_compte("mdupont")

    with pytest.raises(DuplicateKeyError):
        create_user(users, "Dupont", "Marie", "", "mdupont", "secret123", "user", [])


# ---------------------------------------------------------------------------
# delete_blocked_reason
# ---------------------------------------------------------------------------

def test_delete_blocked_reason_son_propre_compte(users, creer_compte):
    """Un utilisateur ne peut pas supprimer son propre compte."""
    creer_compte("admin1", role="admin")
    cible = creer_compte("alice", role="user")

    message = delete_blocked_reason(users, cible, current_username="alice")

    assert message is not None
    assert "propre compte" in message


def test_delete_blocked_reason_dernier_admin(users, creer_compte):
    """Le dernier admin ne peut pas être supprimé."""
    dernier_admin = creer_compte("admin1", role="admin")

    message = delete_blocked_reason(users, dernier_admin, current_username="autre")

    assert message is not None
    assert "dernier" in message


def test_delete_blocked_reason_admin_avec_un_autre_admin(users, creer_compte):
    """Un admin peut être supprimé s'il en reste un autre."""
    admin_a_supprimer = creer_compte("admin1", role="admin")
    creer_compte("admin2", role="admin")

    assert delete_blocked_reason(users, admin_a_supprimer, "admin2") is None


def test_delete_blocked_reason_simple_utilisateur(users, creer_compte):
    """Un simple utilisateur peut être supprimé par un autre compte."""
    creer_compte("admin1", role="admin")
    cible = creer_compte("alice", role="user")

    assert delete_blocked_reason(users, cible, "admin1") is None


# ---------------------------------------------------------------------------
# delete_user
# ---------------------------------------------------------------------------

def test_delete_user(users, creer_compte):
    """Le compte est supprimé : True la première fois, False ensuite."""
    compte = creer_compte("alice")

    assert delete_user(users, compte["_id"]) is True
    assert users.find_one({"username": "alice"}) is None
    # Deuxième suppression : le compte n'existe plus
    assert delete_user(users, compte["_id"]) is False


# ---------------------------------------------------------------------------
# validate_user_update
# ---------------------------------------------------------------------------

def champs_modif_valides(**surcharges) -> dict:
    """Champs d'un formulaire de modification valide, modifiables au cas par cas."""
    champs = {
        "new_username": "alice",
        "new_nom": "Nom",
        "new_prenom": "Prénom",
        "new_role": "user",
        "nb_admins": 2,
    }
    champs.update(surcharges)
    return champs


def test_validate_user_update_valide(users, creer_compte):
    """Un formulaire correct ne renvoie aucune erreur."""
    compte = creer_compte("alice")

    assert validate_user_update(users, compte, **champs_modif_valides()) is None


@pytest.mark.parametrize(
    "champ, mot_cle",
    [
        ("new_username", "utilisateur"),
        ("new_nom", "Le nom ne"),
        ("new_prenom", "Le pr"),
    ],
)
def test_validate_user_update_champ_vide(users, creer_compte, champ, mot_cle):
    """Chaque champ obligatoire vide est refusé."""
    compte = creer_compte("alice")

    message = validate_user_update(
        users, compte, **champs_modif_valides(**{champ: "  "})
    )

    assert message is not None
    assert "vide" in message
    assert mot_cle in message


def test_validate_user_update_username_pris_par_un_autre(users, creer_compte):
    """Reprendre le username d'un autre compte est refusé."""
    compte = creer_compte("alice")
    creer_compte("bob")

    message = validate_user_update(
        users, compte, **champs_modif_valides(new_username="bob")
    )

    assert message is not None
    assert "autre compte" in message


def test_validate_user_update_garder_son_propre_username(users, creer_compte):
    """Garder son propre username n'est pas un doublon."""
    compte = creer_compte("alice")

    assert validate_user_update(
        users, compte, **champs_modif_valides(new_username="alice")
    ) is None


def test_validate_user_update_retirer_role_dernier_admin(users, creer_compte):
    """Le dernier admin ne peut pas devenir simple utilisateur."""
    dernier_admin = creer_compte("admin1", role="admin")

    message = validate_user_update(
        users,
        dernier_admin,
        **champs_modif_valides(new_username="admin1", new_role="user", nb_admins=1),
    )

    assert message is not None
    assert "dernier" in message


def test_validate_user_update_retirer_role_admin_avec_un_autre_admin(
    users, creer_compte
):
    """Un admin peut redevenir simple utilisateur s'il reste un autre admin."""
    admin = creer_compte("admin1", role="admin")
    creer_compte("admin2", role="admin")

    assert validate_user_update(
        users,
        admin,
        **champs_modif_valides(new_username="admin1", new_role="user", nb_admins=2),
    ) is None


# ---------------------------------------------------------------------------
# update_user
# ---------------------------------------------------------------------------

def test_update_user_modifie_les_champs(users, creer_compte):
    """Les champs sont mis à jour en base (espaces retirés, email vide = None)."""
    compte = creer_compte("alice")

    resultat = update_user(
        users,
        compte["_id"],
        new_username=" alice2 ",
        new_nom=" Martin ",
        new_prenom="Alice",
        new_email="   ",
        new_role="admin",
        datasets_access=["dataset_a", "dataset_b"],
    )

    en_base = users.find_one({"_id": compte["_id"]})
    assert resultat is True
    assert en_base["username"] == "alice2"
    assert en_base["nom"] == "Martin"
    assert en_base["email"] is None
    assert en_base["role"] == "admin"
    assert en_base["datasets_access"] == ["dataset_a", "dataset_b"]


def test_update_user_compte_supprime_entre_temps(users):
    """Si le compte n'existe plus, la fonction renvoie False."""
    resultat = update_user(
        users, ObjectId(), "alice", "Nom", "Prénom", "", "user", []
    )

    assert resultat is False


def test_update_user_doublon_leve_une_erreur(users, creer_compte):
    """L'index unique refuse un username déjà pris par un autre compte."""
    compte = creer_compte("alice")
    creer_compte("bob")

    with pytest.raises(DuplicateKeyError):
        update_user(users, compte["_id"], "bob", "Nom", "Prénom", "", "user", [])