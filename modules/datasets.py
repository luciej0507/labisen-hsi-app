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

Une seule connexion SFTP est ouverte pour tout le module, et réutilisée
par tous les appels (voir _obtenir_sftp), au lieu d'en ouvrir une nouvelle
à chaque fois. Comme l'application tourne en continu dans un même
processus, cette connexion reste valable d'un rechargement de page à
l'autre. Si plusieurs admins utilisent le dashboard exactement en même
temps, ils se partagent cette même connexion, ce qui suffit pour un
dashboard d'administration à faible nombre d'utilisateurs simultanés.
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


# Les trois splits attendus dans un dataset (voir la page Mode d'emploi)
SPLITS = ["Train", "Test", "Val"]



# Connexion SFTP partagée par tout le module. Vide au démarrage : elle est
# ouverte au premier appel qui en a besoin, puis réutilisée ensuite.
_connexion = {"sftp": None, "transport": None}


def _connexion_active() -> bool:
    """Indique si la connexion partagée existe et semble toujours active."""
    transport = _connexion["transport"]
    return transport is not None and transport.is_active()


def _obtenir_sftp():
    """
    Renvoie un client SFTP déjà connecté au serveur.

    Réutilise la connexion partagée si elle est toujours active. Sinon
    (premier appel, ou connexion coupée depuis), une nouvelle connexion est
    ouverte et devient la connexion partagée pour les appels suivants.

    Peut lever paramiko.SSHException ou OSError si la connexion échoue.
    """
    if not _connexion_active():
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USERNAME, password=SFTP_PASSWORD)
        _connexion["transport"] = transport
        _connexion["sftp"] = paramiko.SFTPClient.from_transport(transport)
    return _connexion["sftp"]


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
        sftp = _obtenir_sftp()
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

    # Tri alphabétique, dossiers d'abord, pour une lecture plus naturelle
    elements.sort(key=lambda e: (not e["est_dossier"], e["nom"]))
    return elements

def mettre_a_jour_selection(selection: set, chemin: str, coche: bool) -> set:
    """
    Renvoie une nouvelle sélection de chemins, avec `chemin` ajouté si
    `coche` vaut True, ou retiré sinon.

    La sélection d'origine n'est pas modifiée. Cette fonction ne dépend
    pas de Streamlit : c'est l'interface qui l'appelle à chaque clic.
    """
    nouvelle_selection = set(selection)
    if coche:
        nouvelle_selection.add(chemin)
    else:
        nouvelle_selection.discard(chemin)
    return nouvelle_selection


def chemin_relatif(racine: str, chemin: str) -> str:
    """
    Renvoie `chemin` sans le préfixe `racine`, pour un affichage plus court.

    Si `chemin` n'est pas situé sous la racine, il est renvoyé tel quel.
    """
    base = racine.rstrip("/") + "/"
    if chemin.startswith(base):
        return chemin[len(base):]
    return chemin



def get_datasets_autorises(users, username: str) -> list:
    """
    Renvoie la liste des chemins de datasets autorisés pour un utilisateur.
 
    La lecture se fait en base à chaque appel (et non depuis la session),
    pour que les changements faits par l'admin s'appliquent immédiatement.
    Renvoie une liste vide si l'utilisateur n'existe pas ou n'a aucun accès.
    """
    user = users.find_one({"username": username}, {"datasets_access": 1})
    if not user:
        return []
    return user.get("datasets_access") or []
 
 
def _noms(sftp, chemin):
    """Renvoie les noms contenus dans un dossier, ou None s'il est inaccessible."""
    try:
        return sftp.listdir(chemin)
    except IOError:
        return None
 
 
 
# Dossiers dont le nom peut être suivi d'un suffixe (en minuscules).
# Exemple : "HSI-Hybercube" est reconnu comme le dossier "HSI".
DOSSIERS_A_PREFIXE = ("hsi",)
 
 
def _trouver(noms, voulu):
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

 
 
def _resoudre(sftp, base, sous_chemin):
    """
    Descend dans `sous_chemin` (ex : "Annotation/JSON") à partir de `base`,
    en tolérant les différences de casse. Renvoie le vrai chemin, ou None
    si un des dossiers n'existe pas.
    """
    chemin = base
    for partie in sous_chemin.split("/"):
        noms = _noms(sftp, chemin)
        if noms is None:
            return None
        reel = _trouver(noms, partie)
        if reel is None:
            return None
        chemin = f"{chemin.rstrip('/')}/{reel}"
    return chemin
 
 
def _bases(sftp, split_chemin, sous_chemin, extension):
    """
    Renvoie l'ensemble des noms de base (sans l'extension) des fichiers
    d'un sous-dossier qui se terminent par `extension`.
    Ensemble vide si le sous-dossier n'existe pas.
    """
    chemin = _resoudre(sftp, split_chemin, sous_chemin)
    if chemin is None:
        return set()
    noms = _noms(sftp, chemin) or []
    return {
        nom[: -len(extension)]
        for nom in noms
        if nom.lower().endswith(extension)
    }
 
 
def _stats_split(sftp, split_chemin):
    """Calcule les stats d'UN split (Train, Test ou Val)."""
    # Un cube = un fichier .bil dans HSI/
    cubes = _bases(sftp, split_chemin, "HSI", ".bil")
    # Fichiers associés à chaque cube (même nom de base)
    hdr = _bases(sftp, split_chemin, "HSI", ".bil.hdr")
    rgb_png = _bases(sftp, split_chemin, "RGB/PNG", ".png")
    rgb_tiff = _bases(sftp, split_chemin, "RGB/TIFF", ".tiff")
    ann_png = _bases(sftp, split_chemin, "Annotation/PNG", ".png")
    # Le JSON d'annotation est un fichier par split (et non par cube) :
    # on vérifie seulement qu'il y en a au moins un dans le dossier
    ann_json = _bases(sftp, split_chemin, "Annotation/JSON", ".json")
 
    # Un cube est annoté si son masque png existe (même nom de base que le cube)
    annotes = cubes & ann_png
    # Un cube a tous ses fichiers hors annotation s'il est dans les 4 ensembles
    fichiers_ok = cubes & hdr & rgb_png & rgb_tiff
 
    return {
        "cubes": len(cubes),
        "annotes": len(annotes),
        "incomplets": len(cubes - fichiers_ok),
        "json_manquant": len(ann_json) == 0,
    }
 
 
def _resultat(etat, splits=None):
    """Construit le dictionnaire de résultat à partir des stats par split."""
    splits = splits or {}
    total = sum(s["cubes"] for s in splits.values())
    annotes = sum(s["annotes"] for s in splits.values())
    incomplets = sum(s["incomplets"] for s in splits.values())
    # Noms des splits dont le dossier Annotation/JSON ne contient aucun .json
    splits_sans_json = [nom for nom, s in splits.items() if s["json_manquant"]]
    return {
        "etat": etat,
        "cubes_par_split": {nom: s["cubes"] for nom, s in splits.items()},
        "total_cubes": total,
        "annotes": annotes,
        "incomplets": incomplets,
        "splits_sans_json": splits_sans_json,
        "taches": [],
    }
 
 
def calculer_stats(chemin_dataset: str) -> dict:
    """
    Calcule les stats d'un dataset à partir de sa structure sur le serveur.
 
    Utilise la connexion SFTP partagée du module (voir _obtenir_sftp).
    Renvoie un dictionnaire avec les clés :
      - "etat" : "Serveur injoignable", "Introuvable", "Non conforme",
        "À compléter" (il reste des tâches) ou "Complet"
      - "taches" : liste de textes décrivant tout ce qui reste à faire pour
        que le dataset soit complet (vide si "Complet")
      - "cubes_par_split" : nombre de cubes HSI par split trouvé
      - "total_cubes", "annotes", "incomplets" : totaux sur tous les splits
      - "splits_sans_json" : splits dont Annotation/JSON ne contient aucun .json
    """
    try:
        sftp = _obtenir_sftp()
    except (paramiko.SSHException, OSError):
        return _resultat("Serveur injoignable")
 
    splits = {}
    racine = _noms(sftp, chemin_dataset)
    if racine is None:
        return _resultat("Introuvable")

    # On calcule les stats de chaque split présent dans le dataset
    for split in SPLITS:
        reel = _trouver(racine, split)
        if reel is not None:
            chemin_split = f"{chemin_dataset.rstrip('/')}/{reel}"
            splits[split] = _stats_split(sftp, chemin_split)

    resultat = _resultat("", splits)
 
    # Le split est fait si les 3 dossiers existent et contiennent des cubes
    split_fait = len(splits) == len(SPLITS) and all(
        s["cubes"] > 0 for s in splits.values()
    )
 
    # Dossier sans aucun split : il n'y a rien d'autre à évaluer
    if not splits:
        resultat["etat"] = "Non conforme"
        return resultat

    # Liste de TOUT ce qui reste à faire : chaque problème est détecté
    # indépendamment des autres, sans ordre de priorité
    taches = []
    if not split_fait:
        taches.append("Split Train/Test/Val à faire")
    if resultat["incomplets"] > 0:
        taches.append(
            f"{resultat['incomplets']} cube(s) avec des fichiers manquants"
        )
    masques_manquants = resultat["total_cubes"] - resultat["annotes"]
    if masques_manquants > 0:
        taches.append(f"{masques_manquants} masque(s) d'annotation manquant(s)")
    if resultat["splits_sans_json"]:
        taches.append(
            "JSON d'annotation manquant pour : "
            + ", ".join(resultat["splits_sans_json"])
        )

    # Le dataset est complet seulement s'il n'y a plus rien à faire
    resultat["taches"] = taches
    resultat["etat"] = "À compléter" if taches else "Complet"
 
    return resultat