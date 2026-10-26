"""
modules/datasets/stats.py

Calcul de la conformité d'un dataset : nombre de cubes, annotations,
fichiers manquants, état du split Train/Test/Val et liste des tâches
restant à faire. Contient aussi la lecture des cubes et de leurs dimensions.

Les fonctions de ce module lisent le serveur via la connexion partagée
de sftp.py. etat_split et tache_split n'ont aucune dépendance réseau.

Ce module n'importe jamais Streamlit.
"""

import paramiko

from modules.datasets.sftp import obtenir_sftp, lister_noms, trouver, resoudre

# Les trois splits attendus dans un dataset (voir la page Mode d'emploi)
SPLITS = ["Train", "Test", "Val"]

# TEMPORAIRE : accepte aussi les masques .png placés directement dans
# Annotation/ (sans le sous-dossier PNG). À passer à False une fois tous
# les datasets migrés vers la structure Annotation/PNG.
ACCEPTER_ANNOTATION_A_PLAT = True


def _bases(sftp, split_chemin, sous_chemin, extension):
    """
    Renvoie l'ensemble des noms de base (sans l'extension) des fichiers
    d'un sous-dossier qui se terminent par `extension`.
    Ensemble vide si le sous-dossier n'existe pas.
    """
    chemin = resoudre(sftp, split_chemin, sous_chemin)
    if chemin is None:
        return set()
    noms = lister_noms(sftp, chemin) or []
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
    chemin_rgb = resoudre(sftp, split_chemin, "RGB")
    noms_rgb = (lister_noms(sftp, chemin_rgb) or []) if chemin_rgb else []
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

    Utilise la connexion SFTP partagée (voir sftp.obtenir_sftp).
    Renvoie un dictionnaire avec les clés :
      - "etat" : "Serveur injoignable", "Introuvable", "Non conforme",
        "À compléter" (il reste des tâches) ou "Complet"
      - "taches" : liste de textes décrivant tout ce qui reste à faire pour
        que le dataset soit complet (vide si "Complet")
      - "cubes_par_split" : nombre de cubes HSI par split trouvé
      - "total_cubes", "annotes", "incomplets" : totaux sur tous les splits
    """
    try:
        sftp = obtenir_sftp()
    except (paramiko.SSHException, OSError):
        return _resultat("Serveur injoignable")

    splits = {}
    racine = lister_noms(sftp, chemin_dataset)
    if racine is None:
        return _resultat("Introuvable")

    # On calcule les stats de chaque split présent dans le dataset
    for split in SPLITS:
        reel = trouver(racine, split)
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
    racine = lister_noms(sftp, chemin_dataset)
    if racine is None:
        return None
    reel = trouver(racine, split)
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
        sftp = obtenir_sftp()
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
        sftp = obtenir_sftp()
    except (paramiko.SSHException, OSError):
        return None

    chemin_split = _chemin_split(sftp, chemin_dataset, split)
    if chemin_split is None:
        return None
    chemin_hsi = resoudre(sftp, chemin_split, "HSI")
    if chemin_hsi is None:
        return None

    # Fichier d'en-tête du cube, recherché sans tenir compte de la casse
    voulu = f"{nom_cube}.bil.hdr".lower()
    nom_hdr = None
    for nom in lister_noms(sftp, chemin_hsi) or []:
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