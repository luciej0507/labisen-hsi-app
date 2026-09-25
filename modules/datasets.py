"""
modules/datasets.py

Recherche des datasets disponibles sur le serveur de l'école.

Le serveur n'est pas monté localement : on s'y connecte en SFTP (SSH)
pour lister le contenu du dossier partagé.

list_folder_contents ne lit qu'UN SEUL niveau à la fois (jamais de
parcours récursif complet d'un dossier). C'est à l'interface d'appeler
cette fonction niveau par niveau, au fur et à mesure que l'admin
explore l'arborescence, pour rester rapide même sur de gros dossiers.

Ce module n'importe jamais Streamlit, pour rester cohérent avec
modules/users.py et pouvoir être testé indépendamment de l'affichage.
"""

import os
import stat

import paramiko
from dotenv import load_dotenv

load_dotenv()

# Paramètres de connexion au serveur, lus depuis les variables
# d'environnement (.env), comme pour MONGO_URI dans db_mongo.py
SFTP_HOST = os.getenv("SFTP_HOST")
SFTP_PORT = int(os.getenv("SFTP_PORT", "22"))
SFTP_USERNAME = os.getenv("SFTP_USERNAME")
SFTP_PASSWORD = os.getenv("SFTP_PASSWORD")

# Chemin du dossier contenant les datasets sur le serveur distant
DATASETS_REMOTE_PATH = "/mnt/lslteam/SIIRI/CodePythonSIIRI/"


def _connecter_sftp():
    """Ouvre une connexion SFTP et renvoie (client sftp, transport)."""
    transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    transport.connect(username=SFTP_USERNAME, password=SFTP_PASSWORD)
    sftp = paramiko.SFTPClient.from_transport(transport)
    return sftp, transport


def list_folder_contents(chemin: str) -> list:
    """
    Liste le contenu d'UN SEUL niveau d'un dossier distant (sans entrer
    dans les sous-dossiers).

    Renvoie une liste de dictionnaires avec les clés "nom", "chemin" et
    "est_dossier", triée par ordre alphabétique (dossiers d'abord).

    Renvoie une liste vide si la connexion échoue ou si le dossier est
    inaccessible : c'est à l'interface d'afficher un message dans ce cas.
    """
    try:
        sftp, transport = _connecter_sftp()
    except (paramiko.SSHException, OSError):
        return []

    elements = []
    try:
        for entree in sftp.listdir_attr(chemin):
            chemin_entree = f"{chemin.rstrip('/')}/{entree.filename}"
            elements.append(
                {
                    "nom": entree.filename,
                    "chemin": chemin_entree,
                    "est_dossier": stat.S_ISDIR(entree.st_mode),
                }
            )
    except IOError:
        elements = []
    finally:
        sftp.close()
        transport.close()

    # Tri alphabétique, dossiers d'abord, pour une lecture plus naturelle
    elements.sort(key=lambda e: (not e["est_dossier"], e["nom"]))
    return elements