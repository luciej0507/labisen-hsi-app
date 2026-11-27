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
    scripts (par exemple http://10.10.192.11:5000, ou http://mlflow:5000 avec
    Docker). Le serveur écoute sur l'hôte et le port de cette adresse.
  - MLFLOW_URL_PUBLIQUE : adresse de MLflow ouverte dans le navigateur de
    l'utilisateur (lien affiché dans l'interface). Par défaut : la même
    adresse que l'adresse interne.
  - MLFLOW_DEMARRAGE_AUTO : 1 (défaut) pour que le worker démarre MLflow
    lui-même s'il ne tourne pas, 0 si MLflow est lancé à part.
  - MLFLOW_ORIGINES_AUTORISEES : adresses du navigateur autorisées à appeler
    l'API de MLflow, séparées par des virgules. Par défaut : les adresses
    interne et publique. Sans cela, l'interface MLflow affiche
    "Request error INTERNAL_ERROR".

Toute la configuration de MLflow est dans la section "MLflow" ci-dessous.

Ce module n'importe jamais Streamlit.
"""

import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

# Racine du projet (le dossier qui contient modules/, pages/ et worker.py)
RACINE_PROJET = Path(__file__).resolve().parent.parent

# Dossier des fichiers écrits par le worker et lus par l'application
DOSSIER_DONNEES_APP = Path(os.getenv("DOSSIER_DONNEES_APP") or RACINE_PROJET)

# Dossier où sont rangés les runs, la base MLflow et ses artefacts
DOSSIER_ENTRAINEMENTS = DOSSIER_DONNEES_APP / "entrainements"


# ---------------------------------------------------------------------------
# MLflow
# ---------------------------------------------------------------------------

# Adresses de MLflow (sans "/" final, pour pouvoir y ajouter un chemin)
MLFLOW_URL_INTERNE = (os.getenv("MLFLOW_URL_INTERNE") or "http://127.0.0.1:5000").rstrip("/")
MLFLOW_URL_PUBLIQUE = (os.getenv("MLFLOW_URL_PUBLIQUE") or MLFLOW_URL_INTERNE).rstrip("/")

# Hôte et port d'écoute du serveur, déduits de l'adresse interne
MLFLOW_HOTE = urlparse(MLFLOW_URL_INTERNE).hostname or "127.0.0.1"
MLFLOW_PORT = urlparse(MLFLOW_URL_INTERNE).port or 5000

# Le worker démarre-t-il MLflow lui-même ? (1 = oui, 0 = non)
MLFLOW_DEMARRAGE_AUTO = os.getenv("MLFLOW_DEMARRAGE_AUTO", "1") == "1"

# Fichiers du serveur MLflow
MLFLOW_BASE_DONNEES = DOSSIER_ENTRAINEMENTS / "mlflow.db"
MLFLOW_DOSSIER_ARTEFACTS = DOSSIER_ENTRAINEMENTS / "mlartifacts"
MLFLOW_JOURNAL_SERVEUR = DOSSIER_ENTRAINEMENTS / "mlflow_server.log"

# Adresses du navigateur autorisées à appeler l'API de MLflow.
# Par défaut : les adresses interne et publique (sans doublon).
origines_par_defaut = ",".join(sorted({MLFLOW_URL_PUBLIQUE, MLFLOW_URL_INTERNE}))
MLFLOW_ORIGINES_AUTORISEES = os.getenv("MLFLOW_ORIGINES_AUTORISEES") or origines_par_defaut

# MLflow lit cette variable d'environnement au démarrage de son serveur.
# Le processus MLflow lancé par le worker la reçoit automatiquement.
os.environ["MLFLOW_SERVER_CORS_ALLOWED_ORIGINS"] = MLFLOW_ORIGINES_AUTORISEES

# Nom du modèle enregistré dans le Model registry
MLFLOW_NOM_MODELE_REGISTRY = "fastflow_streamlit"