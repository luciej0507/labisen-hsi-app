"""
modules/datasets/sftp.py

Connexion SFTP partagée et petits utilitaires bas niveau.

Le serveur de l'école n'est pas monté localement : on s'y connecte en SFTP
(SSH). Une seule connexion est ouverte pour tout le package, puis réutilisée
par tous les appels (voir obtenir_sftp), au lieu d'en ouvrir une nouvelle à
chaque fois. Comme l'application tourne en continu dans un même processus,
cette connexion reste valable d'un rechargement de page à l'autre.

Ce module est le seul à connaître les paramètres de connexion : les autres
modules du package passent par obtenir_sftp.

Ce module n'importe jamais Streamlit.
"""

import os
import socket
import time

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
DATASETS_REMOTE_PATH = os.getenv(
    "DATASETS_REMOTE_PATH", "/mnt/lslteam/SIIRI/CodePythonSIIRI/"
)

# Durée maximale d'attente (en secondes) pour joindre le serveur. Sans cette
# limite, un serveur éteint fait attendre plusieurs dizaines de secondes.
TIMEOUT_CONNEXION = 5

# Après un échec de connexion, on ne réessaie pas pendant ce délai (en
# secondes) : les appels suivants échouent immédiatement au lieu d'attendre
# à nouveau le timeout.
DELAI_NOUVELLE_TENTATIVE = 30

# Dossiers dont le nom peut être suivi d'un suffixe (en minuscules).
# Exemple : "HSI-Hybercube" est reconnu comme le dossier "HSI".
DOSSIERS_A_PREFIXE = ("hsi",)

# Connexion SFTP partagée. Vide au démarrage : elle est ouverte au premier
# appel qui en a besoin, puis réutilisée ensuite.
_connexion = {"sftp": None, "transport": None}

# Heure (time.time()) du dernier échec de connexion, None si aucun échec
_dernier_echec = {"heure": None}


def _connexion_active() -> bool:
    """Indique si la connexion partagée existe et semble toujours active."""
    transport = _connexion["transport"]
    return transport is not None and transport.is_active()


def obtenir_sftp():
    """
    Renvoie un client SFTP déjà connecté au serveur.

    Réutilise la connexion partagée si elle est toujours active. Sinon
    (premier appel, ou connexion coupée depuis), une nouvelle connexion est
    ouverte et devient la connexion partagée pour les appels suivants.

    Si la dernière tentative a échoué il y a moins de DELAI_NOUVELLE_TENTATIVE
    secondes, aucune nouvelle tentative n'est faite : l'erreur est levée
    tout de suite, pour ne pas attendre le timeout à chaque appel.

    Peut lever paramiko.SSHException ou OSError si la connexion échoue.
    """
    if not _connexion_active():
        # Échec récent : on abandonne immédiatement
        heure = _dernier_echec["heure"]
        if heure is not None and time.time() - heure < DELAI_NOUVELLE_TENTATIVE:
            raise OSError("Serveur injoignable (échec récent)")

        try:
            # Le socket est ouvert avec un timeout court, puis confié à paramiko
            sock = socket.create_connection(
                (SFTP_HOST, SFTP_PORT), timeout=TIMEOUT_CONNEXION
            )
            transport = paramiko.Transport(sock)
            transport.connect(username=SFTP_USERNAME, password=SFTP_PASSWORD)
        except (paramiko.SSHException, OSError):
            # On retient l'heure de l'échec avant de renvoyer l'erreur
            _dernier_echec["heure"] = time.time()
            raise

        _dernier_echec["heure"] = None
        _connexion["transport"] = transport
        _connexion["sftp"] = paramiko.SFTPClient.from_transport(transport)
    return _connexion["sftp"]


def lister_noms(sftp, chemin):
    """Renvoie les noms contenus dans un dossier, ou None s'il est inaccessible."""
    try:
        return sftp.listdir(chemin)
    except IOError:
        return None


def trouver(noms, voulu):
    """
    Cherche un dossier par son nom, sans tenir compte de la casse
    (train = Train).

    Pour les dossiers de DOSSIERS_A_PREFIXE (HSI), on accepte aussi un nom
    qui commence par ce préfixe (HSI-Hybercube), mais seulement si aucun
    nom exact n'existe : le nom exact reste toujours prioritaire.
    """
    # 1) Nom exact, à la casse près
    for nom in noms:
        if nom.lower() == voulu.lower():
            return nom

    # 2) Nom qui commence par le préfixe (tri pour un résultat stable)
    if voulu.lower() in DOSSIERS_A_PREFIXE:
        for nom in sorted(noms):
            if nom.lower().startswith(voulu.lower()):
                return nom

    return None


def resoudre(sftp, base, sous_chemin):
    """
    Descend dans `sous_chemin` (ex : "Annotation/JSON") à partir de `base`,
    en tolérant les différences de casse. Renvoie le vrai chemin, ou None
    si un des dossiers n'existe pas.
    """
    chemin = base
    for partie in sous_chemin.split("/"):
        noms = lister_noms(sftp, chemin)
        if noms is None:
            return None
        reel = trouver(noms, partie)
        if reel is None:
            return None
        chemin = f"{chemin.rstrip('/')}/{reel}"
    return chemin