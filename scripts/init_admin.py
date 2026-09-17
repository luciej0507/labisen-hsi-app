"""
Crée le premier compte Admin, si aucun n'existe déjà.

À exécuter manuellement, une seule fois, après la mise en place de MongoDB

Si un admin existe déjà en base, il ne fait rien et le signale. 
Le mot de passe est demandé de façon interactive (jamais en dur dans le code)
et n'est jamais stocké en clair : seul son hash (bcrypt)
est enregistré dans MongoDB.
"""

import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path

# Permet d'exécuter "python scripts/init_admin.py" depuis la racine du projet
# en trouvant bien le package modules/.
sys.path.append(str(Path(__file__).resolve().parent.parent))

import bcrypt

from modules.db_mongo import get_users_collection

# Connexion à la base Mongo
def main() -> None:
    users = get_users_collection()
    # Vérifie si un compte admin existe déjà
    existing_admin = users.find_one({"role": "admin"})
    if existing_admin:
        print(
            f"Un admin existe déjà ('{existing_admin['username']}'). "
            "Aucune action effectuée."
        )
        return

    print("Aucun admin trouvé. Création du premier compte administrateur.\n")
    # S'il n'y a pas d'admin, on demande le nom d'utilisateur et le mot de passe
    username = input("Nom d'utilisateur admin : ").strip()
    if not username:
        print("Le nom d'utilisateur ne peut pas être vide.")
        return

    if users.find_one({"username": username}):
        print(f"Le nom d'utilisateur '{username}' est déjà pris par un autre compte.")
        return

    password = getpass.getpass("Mot de passe admin : ")
    password_confirm = getpass.getpass("Confirmez le mot de passe : ")

    if not password:
        print("Le mot de passe ne peut pas être vide.")
        return

    if password != password_confirm:
        print("Les mots de passe ne correspondent pas.")
        return
    # Hashage du mot de passe avec bcrypt
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    # Insertion dans la collection "users"
    users.insert_one(
        {
            "username": username,
            # decode() car MongoDB stocke une chaîne, pas des bytes
            "password_hash": password_hash.decode("utf-8"),
            "role": "admin",
            "datasets_access": [],  # un admin n'a pas besoin de restriction de datasets
            "created_at": datetime.now(timezone.utc),
        }
    )

    print(f"\nCompte admin '{username}' créé avec succès.")


if __name__ == "__main__":
    main()