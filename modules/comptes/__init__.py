"""
modules/comptes : tout ce qui concerne les comptes utilisateurs.

Organisation du package :
    - auth.py : authentification et gestion de la session Streamlit
                (connexion, déconnexion, protection des pages par rôle).
    - users.py : logique métier des comptes (création, modification,
                suppression, mots de passe), sans dépendance à Streamlit.
    - user_import.py : logique d'import de comptes depuis un fichier CSV
                     (lecture, analyse des lignes, actions), en fonctions pures.

La connexion à MongoDB ne se trouve pas ici : elle est dans
modules/db_mongo.py, car elle est partagée avec les autres modules.
"""