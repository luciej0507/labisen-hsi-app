"""
modules/users.py

Logique métier liée aux comptes utilisateurs : création, modification,
suppression, import CSV. Ce module n'importe jamais Streamlit, pour que
chaque fonction puisse être testée avec un simple assert, independamment
de l'affichage.

Convention utilisée ici : une fonction de validation renvoie soit None
(tout est valide), soit une chaine de caractères qui est le message
d'erreur à afficher. C'est la page qui décide comment l'afficher.
"""

from datetime import datetime, timezone
from typing import Optional

import bcrypt
from pymongo.errors import DuplicateKeyError, PyMongoError


def ensure_username_index(users) -> bool:
    """
    Crée un index unique sur username, pour que MongoDB refuse lui même
    les doublons même en cas de clics simultanés.
    Renvoie False si l'index n'a pas pu être créé (doublons déjà présents
    en base, par exemple) : l'application continue de fonctionner avec
    ses vérifications habituelles.
    """
    try:
        users.create_index("username", unique=True)
        return True
    except PyMongoError:
        return False


def hash_password(password: str) -> str:
    """Hash bcrypt du mot de passe, prêt à être stocké en base."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def is_password_pending(user: dict) -> bool:
    """
    True si le compte n'a pas encore de mot de passe (compte "en attente",
    créé par import CSV sans mot de passe). Il ne peut pas se connecter.
    """
    return not user.get("password_hash")

def count_pending_users(users) -> int:
    """
    Compte les comptes "en attente" : rôle user et pas encore de mot de passe.
    Ce sont les comptes créés par import CSV.
    En MongoDB, filtrer sur None inclut aussi les comptes où le champ
    password_hash est absent.
    """
    return users.count_documents({"role": "user", "password_hash": None})


def validate_new_password(password: str, password_confirm: str) -> Optional[str]:
    """
    Vérifie la saisie d'un nouveau mot de passe.
    Renvoie un message d'erreur, ou None si tout est valide.
    """
    if not password:
        return "Le mot de passe ne peut pas être vide."
    if password != password_confirm:
        return "Les mots de passe ne correspondent pas."
    return None


def reset_password(users, user_id, password: str) -> bool:
    """
    Définit ou remplace le mot de passe d'un compte (stocké hashé).
    Renvoie True si le compte existait, False s'il a été supprimé entre temps.
    """
    result = users.update_one(
        {"_id": user_id},
        {"$set": {"password_hash": hash_password(password)}},
    )
    return result.matched_count > 0


def format_date(value) -> str:
    """Date au format JJ/MM/AAAA."""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    return str(value) if value else ""


def validate_new_user(nom: str, prenom: str, username: str, password: str,
                       password_confirm: str, users) -> Optional[str]:
    """
    Vérifie les champs du formulaire d'ajout d'un utilisateur.
    Renvoie un message d'erreur, ou None si tout est valide.
    """
    if not nom.strip():
        return "Le nom ne peut pas être vide."
    if not prenom.strip():
        return "Le prénom ne peut pas être vide."
    if not username.strip():
        return "Le nom d'utilisateur ne peut pas être vide."
    if not password:
        return "Le mot de passe ne peut pas être vide."
    if password != password_confirm:
        return "Les mots de passe ne correspondent pas."
    if users.find_one({"username": username.strip()}):
        return "Ce nom d'utilisateur existe déjà."
    return None


def create_user(users, nom: str, prenom: str, email: str, username: str,
                 password: str, role: str, datasets_access: list) -> dict:
    """
    Insère un nouvel utilisateur en base.
    Peut lever DuplicateKeyError si le username existe déjà (cas rare ou
    deux clics simultanés passent la verification de validate_new_user en
    même temps : c'est l'index unique en base qui tranche).
    Renvoie le document inséré, sous la forme utilisée pour le
    récapitulatif affiché à la page.
    """
    document = {
        "nom": nom.strip(),
        "prenom": prenom.strip(),
        "email": email.strip() or None,
        "username": username.strip(),
        "password_hash": hash_password(password),
        "role": role,
        "datasets_access": datasets_access,
        "created_at": datetime.now(timezone.utc),
    }
    users.insert_one(document)
    return {
        "username": document["username"],
        "nom": document["nom"],
        "prenom": document["prenom"],
        "role": document["role"],
        "datasets_access": document["datasets_access"],
    }


def delete_blocked_reason(users, user: dict, current_username: str) -> Optional[str]:
    """Retourne la raison qui interdit la suppression, ou None si c'est permis."""
    if user.get("username") == current_username:
        return "Vous ne pouvez pas supprimer votre propre compte."
    if user.get("role") == "admin" and users.count_documents({"role": "admin"}) <= 1:
        return "Impossible de supprimer le dernier compte admin."
    return None


def delete_user(users, user_id) -> bool:
    """Supprime le compte. Renvoie True si un document a bien été supprimé."""
    result = users.delete_one({"_id": user_id})
    return result.deleted_count == 1


def validate_user_update(users, selected_user: dict, new_username: str,
                          new_nom: str, new_prenom: str, new_role: str,
                          nb_admins: int) -> Optional[str]:
    """
    Vérifie les champs du formulaire de modification d'un compte.
    Renvoie un message d'erreur, ou None si tout est valide.
    """
    if not new_username.strip():
        return "Le nom d'utilisateur ne peut pas être vide."
    if not new_nom.strip():
        return "Le nom ne peut pas être vide."
    if not new_prenom.strip():
        return "Le prénom ne peut pas être vide."
    if users.find_one(
        {"username": new_username.strip(), "_id": {"$ne": selected_user["_id"]}}
    ):
        return "Ce nom d'utilisateur est déjà utilisé par un autre compte."
    if (selected_user.get("role") == "admin" and new_role == "user"
            and nb_admins <= 1):
        return "Impossible de retirer le rôle admin du dernier compte admin."
    return None


def update_user(users, user_id, new_username: str, new_nom: str, new_prenom: str,
                 new_email: str, new_role: str, datasets_access: list) -> bool:
    """
    Met à jour le compte.
    Peut lever DuplicateKeyError si le nouveau username est pris entre
    temps par un autre compte (déjà vérifié une premiere fois par
    validate_user_update).
    Renvoie True si le compte existait et a été mis à jour, False si le
    compte a été supprimé entre temps.
    """
    result = users.update_one(
        {"_id": user_id},
        {
            "$set": {
                "username": new_username.strip(),
                "nom": new_nom.strip(),
                "prenom": new_prenom.strip(),
                "email": new_email.strip() or None,
                "role": new_role,
                "datasets_access": datasets_access,
            }
        },
    )
    return result.matched_count > 0


def create_users_from_rows(users, rows: list) -> tuple:
    """
    Insère les lignes à créer issues de l'import CSV.

    Tous les comptes sont créés "en attente" (password_hash à None), avec
    le rôle "user" et sans dataset : l'admin complète ensuite chaque compte
    depuis la page Comptes utilisateurs.

    Renvoie (created, failed) : created contient les comptes créés,
    failed les lignes que MongoDB a refusées (identifiant devenu déjà
    utilisé entre temps).
    """
    created = []
    failed = []
    now = datetime.now(timezone.utc)

    for row in rows:
        try:
            users.insert_one(
                {
                    "nom": row["nom"],
                    "prenom": row["prenom"],
                    "email": row["email"],
                    "username": row["username"],
                    "password_hash": None,
                    "role": "user",
                    "datasets_access": [],
                    "created_at": now,
                }
            )
        except DuplicateKeyError:
            failed.append(
                {
                    "ligne": row["ligne"],
                    "username": row["username"],
                    "motif": "identifiant déjà utilisé",
                }
            )
            continue

        created.append(
            {
                "nom": row["nom"],
                "prenom": row["prenom"],
                "username": row["username"],
            }
        )

    return created, failed


def update_users_from_rows(users, rows: list) -> tuple:
    """
    Met à jour les comptes existants à partir des lignes de l'import CSV.

    Le compte est retrouvé par son username. Seuls le nom, le prénom et
    l'email (seulement s'il est renseigné) sont modifiés : jamais le rôle,
    le mot de passe ni les datasets.

    Renvoie (updated, failed) : updated contient les comptes mis à jour,
    failed les lignes dont le compte n'existe plus (supprimé entre temps).
    """
    updated = []
    failed = []

    for row in rows:
        # L'email n'est remplacé que s'il est renseigné dans le CSV
        changes = {"nom": row["nom"], "prenom": row["prenom"]}
        if row["email"]:
            changes["email"] = row["email"]

        result = users.update_one({"username": row["username"]}, {"$set": changes})
        if result.matched_count == 0:
            failed.append(
                {
                    "ligne": row["ligne"],
                    "username": row["username"],
                    "motif": "compte introuvable (supprimé entre temps)",
                }
            )
            continue

        updated.append(
            {
                "nom": row["nom"],
                "prenom": row["prenom"],
                "username": row["username"],
            }
        )

    return updated, failed