"""
modules/config.py

Chemins et adresses communs à l'application et au worker, lus dans le
fichier .env (comme MONGO_URI dans db_mongo.py).

Variables lues :
  - DOSSIER_DONNEES_APP : dossier où sont écrits les fichiers de suivi du
    patching (suivi_patching/) et les entraînements (entrainements/).
    Par défaut : la racine du projet. L'application et le worker doivent
    voir le même dossier.
  - MLFLOW_URL_INTERNE : adresse de MLflow utilisée par le worker et les
    scripts (par exemple http://127.0.0.1:5000, ou http://mlflow:5000 avec
    Docker).
  - MLFLOW_URL_PUBLIQUE : adresse de MLflow ouverte dans le navigateur de
    l'utilisateur (lien affiché dans l'interface). Par défaut : la même
    adresse que l'adresse interne.
  - MLFLOW_DEMARRAGE_AUTO : 1 (défaut) pour que le worker démarre MLflow
    lui-même s'il ne tourne pas, 0 si MLflow est lancé à part.

Ce module n'importe jamais Streamlit.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Racine du projet (le dossier qui contient modules/, pages/ et worker.py)
RACINE_PROJET = Path(__file__).resolve().parent.parent

# Dossier des fichiers écrits par le worker et lus par l'application
DOSSIER_DONNEES_APP = Path(os.getenv("DOSSIER_DONNEES_APP") or RACINE_PROJET)

# Adresses de MLflow (sans "/" final, pour pouvoir y ajouter un chemin)
MLFLOW_URL_INTERNE = (os.getenv("MLFLOW_URL_INTERNE") or "http://127.0.0.1:5000").rstrip("/")
MLFLOW_URL_PUBLIQUE = (os.getenv("MLFLOW_URL_PUBLIQUE") or MLFLOW_URL_INTERNE).rstrip("/")

# Le worker démarre-t-il MLflow lui-même ? (1 = oui, 0 = non)
MLFLOW_DEMARRAGE_AUTO = os.getenv("MLFLOW_DEMARRAGE_AUTO", "1") == "1"
