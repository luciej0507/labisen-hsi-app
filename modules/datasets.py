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
import socket
import stat
import time

import posixpath
import re
import zipfile

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

# Un nom (de dataset ou d'utilisateur) ne contient que des lettres, des
# chiffres, des tirets et des underscores : pas de "/" ni de ".."
MOTIF_NOM = re.compile(r"^[A-Za-z0-9_-]+$")


# Les trois splits attendus dans un dataset (voir la page Mode d'emploi)
SPLITS = ["Train", "Test", "Val"]

# TEMPORAIRE : accepte aussi les masques .png placés directement dans
# Annotation/ (sans le sous-dossier PNG). À passer à False une fois tous
# les datasets migrés vers la structure Annotation/PNG.
ACCEPTER_ANNOTATION_A_PLAT = True



# Connexion SFTP partagée par tout le module. Vide au démarrage : elle est
# ouverte au premier appel qui en a besoin, puis réutilisée ensuite.
_connexion = {"sftp": None, "transport": None}

# Durée maximale d'attente (en secondes) pour joindre le serveur. Sans cette
# limite, un serveur éteint fait attendre plusieurs dizaines de secondes.
TIMEOUT_CONNEXION = 5

# Après un échec de connexion, on ne réessaie pas pendant ce délai (en
# secondes) : les appels suivants échouent immédiatement au lieu d'attendre
# à nouveau le timeout.
DELAI_NOUVELLE_TENTATIVE = 30

# Heure (time.time()) du dernier échec de connexion, None si aucun échec
_dernier_echec = {"heure": None}


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
    # Les photos RGB (.png) sont directement dans le dossier RGB
    rgb = _bases(sftp, split_chemin, "RGB", ".png")
    ann_png = _bases(sftp, split_chemin, "Annotation/PNG", ".png")
    # Règle temporaire : on accepte aussi les masques directement dans Annotation/
    if ACCEPTER_ANNOTATION_A_PLAT:
        ann_png = ann_png | _bases(sftp, split_chemin, "Annotation", ".png")

 
    # Un cube est annoté si son masque png existe (même nom de base que le cube)
    annotes = cubes & ann_png
    # Ancienne structure : le dossier RGB contient encore des sous-dossiers
    # PNG ou TIFF au lieu des photos directement
    chemin_rgb = _resoudre(sftp, split_chemin, "RGB")
    noms_rgb = (_noms(sftp, chemin_rgb) or []) if chemin_rgb else []
    ancienne_structure = any(nom.lower() in ("png", "tiff") for nom in noms_rgb)

    # Un cube a tous ses fichiers hors annotation s'il est dans les 3 ensembles.
    # Pour l'ancienne structure, on ignore les photos RGB : le problème est
    # signalé à part, pour ne pas afficher de faux "fichiers manquants".
    if ancienne_structure:
        fichiers_ok = cubes & hdr
    else:
        fichiers_ok = cubes & hdr & rgb
 
    return {
        "cubes": len(cubes),
        "annotes": len(annotes),
        "incomplets": len(cubes - fichiers_ok),
        "ancienne_structure": ancienne_structure,
    }
 
 
def _resultat(etat, splits=None):
    """Construit le dictionnaire de résultat à partir des stats par split."""
    splits = splits or {}
    total = sum(s["cubes"] for s in splits.values())
    annotes = sum(s["annotes"] for s in splits.values())
    incomplets = sum(s["incomplets"] for s in splits.values())
    # Vrai si au moins un split utilise encore l'ancienne structure RGB
    ancienne_structure = any(s["ancienne_structure"] for s in splits.values())
    return {
        "etat": etat,
        "cubes_par_split": {nom: s["cubes"] for nom, s in splits.items()},
        "total_cubes": total,
        "annotes": annotes,
        "incomplets": incomplets,
        "ancienne_structure": ancienne_structure,
        "taches": [],
    }
 
 
def etat_split(cubes_par_split: dict) -> str:
    """
    Renvoie l'état du split Train/Test/Val : "Fait", "Incomplet" ou "Non fait".

    - "Fait" : les 3 splits contiennent au moins un cube.
    - "Incomplet" : au moins un split contient des cubes, mais pas les 3.
    - "Non fait" : aucun split ne contient de cube.

    Un split dont le dossier est absent compte comme un split sans cube.
    """
    # Splits qui contiennent au moins un cube (.get gère les dossiers absents)
    remplis = [nom for nom in SPLITS if cubes_par_split.get(nom, 0) > 0]

    if len(remplis) == len(SPLITS):
        return "Fait"
    if remplis:
        return "Incomplet"
    return "Non fait"


def tache_split(cubes_par_split: dict):
    """
    Renvoie le texte de la tâche liée au split, ou None si le split est fait.

    Pour un split incomplet, le texte distingue les dossiers absents
    des dossiers présents mais vides.
    """
    etat = etat_split(cubes_par_split)
    if etat == "Fait":
        return None
    if etat == "Non fait":
        return "Split Train/Test/Val à faire"

    # Split incomplet : on précise ce qui manque
    absents = [nom for nom in SPLITS if nom not in cubes_par_split]
    vides = [nom for nom in SPLITS if cubes_par_split.get(nom) == 0]
    details = []
    if absents:
        details.append("dossier absent : " + ", ".join(absents))
    if vides:
        details.append("dossier vide : " + ", ".join(vides))
    return "Split incomplet (" + "; ".join(details) + ")"


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
 
 
    # Dossier sans aucun split : il n'y a rien d'autre à évaluer
    if not splits:
        resultat["etat"] = "Non conforme"
        return resultat

    # Liste de TOUT ce qui reste à faire : chaque problème est détecté
    # indépendamment des autres, sans ordre de priorité
    taches = []
    message_split = tache_split(resultat["cubes_par_split"])
    if message_split:
        taches.append(message_split)
    if resultat["ancienne_structure"]:
        taches.append(
            "Ancienne structure RGB à migrer (retirer les dossiers PNG et TIFF)"
        )
    if resultat["incomplets"] > 0:
        taches.append(
            f"{resultat['incomplets']} cube(s) avec des fichiers manquants"
        )
    masques_manquants = resultat["total_cubes"] - resultat["annotes"]
    if masques_manquants > 0:
        taches.append(f"{masques_manquants} masque(s) d'annotation manquant(s)")

    # Le dataset est complet seulement s'il n'y a plus rien à faire
    resultat["taches"] = taches
    resultat["etat"] = "À compléter" if taches else "Complet"
 
    return resultat


def _chemin_split(sftp, chemin_dataset: str, split: str):
    """
    Renvoie le vrai chemin du dossier d'un split (Train, Test ou Val),
    sans tenir compte de la casse, ou None s'il n'existe pas.
    """
    racine = _noms(sftp, chemin_dataset)
    if racine is None:
        return None
    reel = _trouver(racine, split)
    if reel is None:
        return None
    return f"{chemin_dataset.rstrip('/')}/{reel}"
 
 
def lister_cubes(chemin_dataset: str, split: str) -> list:
    """
    Liste les cubes HSI d'un split (un cube = un fichier .bil dans HSI/).
 
    Renvoie les noms de base (sans l'extension), triés par ordre alphabétique.
    Renvoie une liste vide si le serveur est injoignable ou si le split
    n'existe pas : c'est à l'interface d'afficher un message dans ce cas.
    """
    try:
        sftp = _obtenir_sftp()
    except (paramiko.SSHException, OSError):
        return []
 
    chemin_split = _chemin_split(sftp, chemin_dataset, split)
    if chemin_split is None:
        return []
 
    return sorted(_bases(sftp, chemin_split, "HSI", ".bil"))
 
 
def lire_dimensions(chemin_dataset: str, split: str, nom_cube: str) -> dict:
    """
    Lit les dimensions d'un cube dans son fichier d'en-tête (.bil.hdr).
 
    Renvoie {"lignes": int, "colonnes": int, "bandes": int}, ou None si
    le fichier est introuvable ou illisible.
    """
    try:
        sftp = _obtenir_sftp()
    except (paramiko.SSHException, OSError):
        return None
 
    chemin_split = _chemin_split(sftp, chemin_dataset, split)
    if chemin_split is None:
        return None
    chemin_hsi = _resoudre(sftp, chemin_split, "HSI")
    if chemin_hsi is None:
        return None
 
    # Fichier d'en-tête du cube, recherché sans tenir compte de la casse
    voulu = f"{nom_cube}.bil.hdr".lower()
    nom_hdr = None
    for nom in _noms(sftp, chemin_hsi) or []:
        if nom.lower() == voulu:
            nom_hdr = nom
            break
    if nom_hdr is None:
        return None
 
    # Lecture du texte de l'en-tête
    try:
        with sftp.open(f"{chemin_hsi.rstrip('/')}/{nom_hdr}", "r") as fichier:
            texte = fichier.read().decode("utf-8", errors="ignore")
    except IOError:
        return None
 
    # Les lignes de l'en-tête ont la forme "cle = valeur"
    valeurs = {}
    for ligne in texte.splitlines():
        if "=" in ligne:
            cle, valeur = ligne.split("=", 1)
            valeurs[cle.strip().lower()] = valeur.strip()
 
    try:
        return {
            "lignes": int(valeurs["lines"]),
            "colonnes": int(valeurs["samples"]),
            "bandes": int(valeurs["bands"]),
        }
    except (KeyError, ValueError):
        return None



def nom_valide(nom: str) -> bool:
    """Indique si un nom est utilisable comme nom de dossier sur le serveur."""
    return bool(MOTIF_NOM.match(nom or ""))
 
 

def dossier_utilisateur(username: str) -> str:
    """Renvoie le dossier personnel d'un utilisateur : <racine>/<username>."""
    return f"{DATASETS_REMOTE_PATH.rstrip('/')}/{username}"
 
 
def chemin_dataset_utilisateur(username: str, nom_dataset: str) -> str:
    """Renvoie le chemin d'un dataset : <racine>/<username>/<nom_dataset>."""
    return f"{dossier_utilisateur(username)}/{nom_dataset}"
 
 
def ajouter_dataset_acces(users, username: str, chemin: str) -> None:
    """
    Ajoute un chemin dans la liste datasets_access de l'utilisateur.
 
    $addToSet n'ajoute le chemin que s'il n'y est pas déjà (pas de doublon).
    """
    users.update_one(
        {"username": username},
        {"$addToSet": {"datasets_access": chemin}},
    )
 
 
def creer_dossier_distant(sftp, chemin: str) -> None:
    """Crée un dossier sur le serveur, ainsi que ses parents s'ils manquent."""
    courant = ""
    for morceau in chemin.strip("/").split("/"):
        courant += "/" + morceau
        try:
            # Le dossier existe déjà : rien à faire
            sftp.stat(courant)
        except IOError:
            sftp.mkdir(courant)
 
 
def supprimer_dossier_distant(sftp, chemin: str) -> None:
    """
    Supprime un dossier et tout son contenu sur le serveur.
 
    Sert uniquement à nettoyer un dataset à moitié envoyé après une erreur.
    """
    for entree in sftp.listdir_attr(chemin):
        chemin_entree = f"{chemin}/{entree.filename}"
        if stat.S_ISDIR(entree.st_mode):
            supprimer_dossier_distant(sftp, chemin_entree)
        else:
            sftp.remove(chemin_entree)
    sftp.rmdir(chemin)
 
 
def _preparer_entrees(archive):
    """
    Prépare la liste des éléments d'une archive zip à envoyer.
 
    Renvoie (entrees, erreur) :
      - entrees : liste de (info_zip, chemin_relatif)
      - erreur : texte d'erreur, ou None si tout va bien
 
    Le contrôle se fait AVANT tout envoi, pour ne rien écrire sur le serveur
    si l'archive est suspecte.
    """
    # On écarte les fichiers parasites ajoutés par macOS
    infos = [
        i for i in archive.infolist()
        if "__MACOSX" not in i.filename.split("/")
        and not i.filename.endswith(".DS_Store")
    ]
    if not infos:
        return None, "L'archive est vide."
 
    # Si l'archive contient un seul dossier qui englobe tout (et que ce n'est
    # pas Train, Test ou Val), on l'enlève des chemins
    premiers = {i.filename.split("/")[0] for i in infos}
    prefixe = ""
    if len(premiers) == 1:
        seul = premiers.pop()
        if seul.lower() not in [s.lower() for s in SPLITS]:
            prefixe = seul + "/"
 
    entrees = []
    for info in infos:
        relatif = info.filename
        if prefixe and relatif.startswith(prefixe):
            relatif = relatif[len(prefixe):]
        relatif = relatif.rstrip("/")
        if not relatif:
            continue
 
        # Protection "zip slip" : aucun chemin absolu ni remontant (..)
        parties = relatif.split("/")
        if relatif.startswith("/") or "\\" in relatif or ".." in parties:
            return None, "L'archive contient un chemin non autorisé : " + info.filename
        entrees.append((info, relatif))
 
    if not entrees:
        return None, "L'archive est vide."
    return entrees, None
 
 
def envoyer_zip(fichier_zip, username: str, nom_dataset: str):
    """
    Envoie le contenu d'une archive zip sur le serveur, dans l'espace de
    l'utilisateur : <racine>/<username>/<nom_dataset>/.
 
    `fichier_zip` est l'objet renvoyé par st.file_uploader. Les fichiers sont
    envoyés directement depuis la mémoire, sans passer par le disque local.
 
    Renvoie (succes, message, chemin) : `chemin` vaut None en cas d'échec.
    Un dataset qui existe déjà n'est jamais écrasé.
    """
    # Vérification des noms (ils servent à construire un chemin)
    if not nom_valide(nom_dataset):
        return False, (
            "Nom invalide : utilisez uniquement des lettres, des chiffres, "
            "des tirets et des underscores."
        ), None
    if not nom_valide(username):
        return False, "Le nom d'utilisateur ne peut pas servir de nom de dossier.", None
 
    chemin = chemin_dataset_utilisateur(username, nom_dataset)
 
    # Ouverture et contrôle de l'archive
    try:
        archive = zipfile.ZipFile(fichier_zip)
    except zipfile.BadZipFile:
        return False, "Le fichier n'est pas une archive zip valide.", None
 
    entrees, erreur = _preparer_entrees(archive)
    if erreur:
        return False, erreur, None
 
    # Connexion partagée au serveur
    try:
        sftp = _obtenir_sftp()
    except (paramiko.SSHException, OSError):
        return False, "Serveur injoignable. Réessayez dans un instant.", None
 
    # Refus si le dataset existe déjà
    try:
        sftp.stat(chemin)
        return False, "Un dataset portant ce nom existe déjà.", None
    except IOError:
        pass
 
    # Envoi : on recrée l'arborescence puis on envoie chaque fichier
    try:
        creer_dossier_distant(sftp, chemin)
        dossiers_crees = set()
        for info, relatif in entrees:
            cible = f"{chemin}/{relatif}"
            if info.is_dir():
                creer_dossier_distant(sftp, cible)
                continue
            # Le dossier parent du fichier est créé une seule fois
            dossier = posixpath.dirname(cible)
            if dossier not in dossiers_crees:
                creer_dossier_distant(sftp, dossier)
                dossiers_crees.add(dossier)
            with archive.open(info) as source:
                sftp.putfo(source, cible)
    except (paramiko.SSHException, OSError) as erreur_envoi:
        # On nettoie le dataset à moitié envoyé, pour pouvoir réessayer
        try:
            supprimer_dossier_distant(sftp, chemin)
        except (paramiko.SSHException, OSError):
            pass
        return False, f"L'envoi a échoué : {erreur_envoi}", None
 
    return True, f"Le dataset « {nom_dataset} » a été envoyé ({len(entrees)} éléments).", chemin


def ajouter_dataset(users, fichier_zip, username: str, nom_dataset: str):
    """
    Ajoute un dataset pour un utilisateur : envoie l'archive zip sur le
    serveur, puis donne l'accès à l'utilisateur en base si l'envoi a réussi.
 
    Renvoie (succes, message), le message étant destiné à l'affichage.
    """
    succes, message, chemin = envoyer_zip(fichier_zip, username, nom_dataset)
    if succes:
        ajouter_dataset_acces(users, username, chemin)
    return succes, message

