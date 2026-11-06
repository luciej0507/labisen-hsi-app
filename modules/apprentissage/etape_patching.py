"""
modules/apprentissage/etape_patching.py

Étape 2 de la page Apprentissage : patching. Cette étape permet de choisir
une version de patches déjà préparée ou de lancer un nouveau patching.

Les accès au serveur et les calculs sur les patches sont dans
modules/versions_patching.py : ce fichier ne fait que préparer ce que la page affiche.
"""

import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import yaml

from modules.datasets.stats import SPLITS, lire_dimensions, lister_cubes
from modules.versions_patching import estimer_nb_patches, lister_versions, splits_non_patches

# Choix de split source pour le patching : un split, ou tous ceux à patcher
TOUS_LES_SPLITS = "Tous les splits"
TOUS_LES_SPLITS_RESTANTS = "Tous les splits restants"

# Split indispensable pour utiliser une version à l'entraînement
SPLIT_ENTRAINEMENT = "Train"

# Catalogue fixe des formats de patches proposés à l'utilisateur. Le même
# fichier est lu par data_utils.py au moment du patching.
CONFIG_FORMATS = Path("config.yaml")


# ---------------------------------------------------------------------------
# Versions déjà préparées
# ---------------------------------------------------------------------------


def lire_versions(chemin_dataset: str):
    """
    Renvoie les versions déjà préparées d'un dataset (liste vide s'il n'y
    en a aucune), ou None si le serveur est injoignable.
    """
    try:
        return lister_versions(chemin_dataset)
    except ConnectionError:
        return None


def lignes_versions(versions: list) -> list:
    """
    Prépare les lignes du tableau des versions déjà préparées : une ligne
    par format, une colonne par split (fractions de CSV disponibles, ou
    "Non patché") et la date de création sans l'heure.

    Le format w1 est placé en premier. Le tri est stable : les autres
    formats gardent leur ordre.
    """
    versions = sorted(versions, key=lambda v: not v["nom"].startswith("w1_"))
    lignes = []
    for version in versions:
        ligne = {"Format": version["nom"]}
        for split in SPLITS:
            if split in version["fractions"]:
                fractions = version["fractions"][split]
                # Split patché : on liste les fractions (ou "Patché" si illisibles)
                ligne[split] = ", ".join(f"{f} %" for f in fractions) or "Patché"
            else:
                ligne[split] = "Non patché"
        date = datetime.fromisoformat(version["date_creation"])
        ligne["Créé le"] = date.strftime("%d/%m/%Y")
        lignes.append(ligne)
    return lignes


def libelles_versions(versions: list) -> dict:
    """
    Renvoie le texte affiché dans la liste de choix pour chaque version,
    sous la forme {nom: "nom (Train, Test)"}.
    """
    return {
        v["nom"]: f"{v['nom']} ({', '.join(v['splits_prets'])})" for v in versions
    }


def trouver_version(versions: list, nom: str):
    """Renvoie la version qui porte ce nom, ou None."""
    return next((v for v in versions if v["nom"] == nom), None)


def version_utilisable(version: dict) -> bool:
    """
    Indique si une version peut servir à l'entraînement : le split Train
    doit être patché.
    """
    return SPLIT_ENTRAINEMENT in version["splits_prets"]


# ---------------------------------------------------------------------------
# Nouveau patching
# ---------------------------------------------------------------------------


def nom_dossier_format(
    n_lines, patch_size, stride_lines, stride_cols, full_width, largeur=None
) -> str:
    """
    Construit le nom du dossier d'une version à partir du format choisi.

    En largeur complète, le nom contient la largeur des cubes (voir
    largeur_commune) à la place de patch_size et de stride_cols.
    """
    if full_width:
        return f"w{n_lines}_h{largeur}_sl{stride_lines}_sc{largeur}"
    return f"w{n_lines}_h{patch_size}_sl{stride_lines}_sc{stride_cols}"


def construire_parametres(n_lines, patch_size, stride_lines, stride_cols, full_width) -> dict:
    """
    Regroupe les paramètres du format dans un dictionnaire.

    En largeur complète, patch_size et stride_cols ne s'appliquent pas :
    ils valent None.
    """
    return {
        "n_lines": n_lines,
        "patch_size": None if full_width else patch_size,
        "stride_lines": stride_lines,
        "stride_cols": None if full_width else stride_cols,
        "full_width": full_width,
    }


def splits_restants(versions: list, nom_dossier: str) -> list:
    """
    Renvoie les splits qui ne sont pas encore patchés pour ce format.

    Une liste vide signifie que le format est entièrement patché : on ne
    propose pas de le refaire.
    """
    return splits_non_patches(versions, nom_dossier)


def splits_deja_patches(restants: list) -> list:
    """Renvoie les splits déjà patchés, c'est-à-dire ceux qui ne sont pas dans `restants`."""
    return [s for s in SPLITS if s not in restants]


def options_split_source(restants: list) -> list:
    """
    Renvoie les choix du split source : un choix par split restant, précédé
    de "Tous les splits" (ou "Tous les splits restants" si certains sont
    déjà patchés) quand il y en a plusieurs.
    """
    if len(restants) <= 1:
        return list(restants)
    tous = TOUS_LES_SPLITS if len(restants) == len(SPLITS) else TOUS_LES_SPLITS_RESTANTS
    return [tous] + list(restants)


def splits_a_patcher(choix: str, restants: list) -> list:
    """Renvoie la liste des splits à patcher selon le choix de l'utilisateur."""
    if choix in (TOUS_LES_SPLITS, TOUS_LES_SPLITS_RESTANTS):
        return list(restants)
    return [choix]


def charger_formats() -> dict:
    """
    Lit le catalogue des formats dans config.yaml.

    Renvoie {libellé: paramètres}, avec un libellé comme "w100 h100 sl50 sc50"
    (w = n_lines, h = patch_size, sl = stride_lines, sc = stride_cols).
    Lève FileNotFoundError si le fichier est absent, ValueError s'il est illisible.
    """
    try:
        with open(CONFIG_FORMATS, encoding="utf-8") as fichier:
            config = yaml.safe_load(fichier)
        formats = {}
        for fmt in config["patch_formats"]:
            libelle = (
                f"w{fmt['n_lines']} h{fmt['patch_size']} "
                f"sl{fmt['stride_lines']} sc{fmt['stride_cols']}"
            )
            formats[libelle] = {
                "n_lines": fmt["n_lines"],
                "patch_size": fmt["patch_size"],
                "stride_lines": fmt["stride_lines"],
                "stride_cols": fmt["stride_cols"],
            }
    except (yaml.YAMLError, KeyError, TypeError) as erreur:
        raise ValueError(f"Catalogue des formats illisible : {erreur}") from erreur
    return formats


def formats_choisis(catalogue: dict, libelles: list, full_width: bool, largeur=None) -> list:
    """
    Prépare les formats cochés par l'utilisateur.

    Renvoie une liste de dictionnaires avec :
      - "libelle" : texte affiché dans la liste de choix
      - "nom_catalogue" : nom du format dans le catalogue, transmis au script
      - "nom_dossier" : nom du dossier créé (il contient la largeur des cubes
        en largeur complète)
      - "parametres" : paramètres du format (voir construire_parametres)

    La largeur complète est choisie une seule fois et s'applique à tous les formats.
    """
    choisis = []
    for libelle in libelles:
        fmt = catalogue[libelle]
        n_lines, patch_size = fmt["n_lines"], fmt["patch_size"]
        stride_lines, stride_cols = fmt["stride_lines"], fmt["stride_cols"]
        choisis.append({
            "libelle": libelle,
            "nom_catalogue": nom_dossier_format(
                n_lines, patch_size, stride_lines, stride_cols, False
            ),
            "nom_dossier": nom_dossier_format(
                n_lines, patch_size, stride_lines, stride_cols, full_width, largeur
            ),
            "parametres": construire_parametres(
                n_lines, patch_size, stride_lines, stride_cols, full_width
            ),
        })
    return choisis


def formats_a_patcher(versions: list, choisis: list) -> list:
    """
    Garde les formats qui ne sont pas encore entièrement patchés.

    Un format déjà patché pour tous les splits n'est pas proposé une seconde fois.
    """
    return [f for f in choisis if splits_restants(versions, f["nom_dossier"])]


def splits_restants_formats(versions: list, choisis: list) -> list:
    """
    Renvoie les splits à patcher pour au moins un des formats choisis, dans
    l'ordre habituel (Train, Test, Val).

    Le script ignore ensuite les splits déjà patchés pour un format donné.
    """
    restants = set()
    for fmt in choisis:
        restants.update(splits_restants(versions, fmt["nom_dossier"]))
    return [s for s in SPLITS if s in restants]


# ---------------------------------------------------------------------------
# Dimensions des cubes, aperçu et lancement
# ---------------------------------------------------------------------------


def lire_dimensions_dataset(chemin_dataset: str) -> dict:
    """
    Lit les dimensions de tous les cubes du dataset, une seule fois.

    Renvoie {split: {nom du cube: dimensions}}, où les dimensions valent
    None si elles sont illisibles. Un split introuvable (ou un serveur
    injoignable) donne un dictionnaire vide.
    """
    dimensions = {}
    for split in SPLITS:
        dimensions[split] = {
            cube: lire_dimensions(chemin_dataset, split, cube)
            for cube in lister_cubes(chemin_dataset, split)
        }
    return dimensions


def largeur_commune(dimensions_dataset: dict):
    """
    Cherche la largeur (nombre de colonnes) commune à tous les cubes.

    Renvoie un couple (largeur, problème). Le problème est un texte à
    afficher quand la largeur ne peut pas être déterminée (dimensions
    illisibles ou cubes de largeurs différentes), sinon None.
    """
    largeurs = {
        dims["colonnes"]
        for cubes in dimensions_dataset.values()
        for dims in cubes.values()
        if dims is not None
    }
    if not largeurs:
        return None, "Dimensions des cubes illisibles : la largeur complète est indisponible."
    if len(largeurs) > 1:
        liste = ", ".join(str(largeur) for largeur in sorted(largeurs))
        return None, (
            f"Les cubes n'ont pas tous la même largeur ({liste}) : "
            "la largeur complète est impossible pour ce dataset."
        )
    return largeurs.pop(), None


def apercu_patching(dimensions_dataset: dict, versions: list, formats: list, splits: list) -> dict:
    """
    Estime le résultat du patching avant de le lancer, pour les formats choisis.

    Un split déjà patché pour un format n'est pas compté pour ce format (le
    script l'ignore). Renvoie un dictionnaire avec :
      - "nb_cubes" : nombre de cubes à patcher (chaque cube n'est lu qu'une
        fois, même pour plusieurs formats)
      - "total_patches" : nombre total de patches estimés
      - "patches_par_format" : nombre de patches estimés par format {libellé: nombre}
      - "illisibles" : nombre de cubes dont les dimensions sont illisibles
        (ils ne sont pas comptés dans l'estimation)
    """
    # Splits réellement à faire pour chaque format
    splits_par_format = {}
    for fmt in formats:
        restants = splits_restants(versions, fmt["nom_dossier"])
        splits_par_format[fmt["libelle"]] = [s for s in splits if s in restants]

    # Cubes : un cube est lu une seule fois s'il est utile à au moins un format
    splits_utiles = [
        s for s in splits if any(s in liste for liste in splits_par_format.values())
    ]
    nb_cubes = sum(len(dimensions_dataset.get(s, {})) for s in splits_utiles)
    illisibles = sum(
        1
        for s in splits_utiles
        for dimensions in dimensions_dataset.get(s, {}).values()
        if dimensions is None
    )

    # Patches : estimation format par format
    patches_par_format = {}
    for fmt in formats:
        total = 0
        for split in splits_par_format[fmt["libelle"]]:
            for dimensions in dimensions_dataset.get(split, {}).values():
                estimation = estimer_nb_patches(dimensions, fmt["parametres"])
                if estimation is not None:
                    total += estimation
        patches_par_format[fmt["libelle"]] = total

    return {
        "nb_cubes": nb_cubes,
        "total_patches": sum(patches_par_format.values()),
        "patches_par_format": patches_par_format,
        "illisibles": illisibles,
    }


# ---------------------------------------------------------------------------
# Lancement en arrière-plan et suivi
#
# Le patching est un processus indépendant de l'application : Streamlit le
# lance, puis lit seulement son fichier de suivi (JSON). Pour passer sur le
# serveur, il suffira de remplacer lancer_patching, lire_suivi,
# processus_actif et annuler_patching par des versions SSH.
# ---------------------------------------------------------------------------

# Script de patching et interpréteur Python qui le lance. L'interpréteur doit
# disposer de torch, spectral, pandas, etc. (à adapter selon votre installation).
SCRIPT_PATCHING = Path("scripts_serveur/data_utils.py")
PYTHON_PATCHING = sys.executable

# Dossier où sont écrits le fichier de suivi et le journal de chaque patching
DOSSIER_SUIVI = Path("suivi_patching")


def base_fichiers_job(chemin_dataset) -> str:
    """
    Renvoie le début du nom des fichiers du job d'un dataset (sans extension).

    Le nom est déduit du dataset : on retrouve donc le job après un
    rechargement de la page. Il y a un seul job à la fois par dataset.
    """
    empreinte = hashlib.md5(str(chemin_dataset).encode("utf-8")).hexdigest()[:10]
    return str(DOSSIER_SUIVI / f"{Path(chemin_dataset).name}_{empreinte}")


def chemin_suivi(chemin_dataset) -> Path:
    """Renvoie le chemin du fichier de suivi (JSON) du job d'un dataset."""
    return Path(base_fichiers_job(chemin_dataset) + ".json")


def chemin_journal(chemin_dataset) -> Path:
    """Renvoie le chemin du journal (sortie texte du script) du job d'un dataset."""
    return Path(base_fichiers_job(chemin_dataset) + ".log")


def ecrire_suivi_local(chemin_dataset, suivi: dict):
    """Écrit le fichier de suivi (fichier temporaire puis renommage, jamais lu à moitié)."""
    fichier = chemin_suivi(chemin_dataset)
    fichier.parent.mkdir(parents=True, exist_ok=True)
    temporaire = Path(str(fichier) + ".tmp")
    temporaire.write_text(json.dumps(suivi, ensure_ascii=False), encoding="utf-8")
    os.replace(temporaire, fichier)


def lire_suivi(chemin_dataset):
    """Renvoie le contenu du fichier de suivi, ou None s'il n'existe pas ou est illisible."""
    try:
        with open(chemin_suivi(chemin_dataset), encoding="utf-8") as fichier:
            return json.load(fichier)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def processus_actif(pid) -> bool:
    """Indique si un processus existe encore (envoi du signal 0, qui ne fait rien)."""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Le processus existe mais appartient à un autre utilisateur
        return True
    return True


def etat_job(chemin_dataset):
    """
    Renvoie le suivi du job d'un dataset, ou None s'il n'y en a pas.

    Si le fichier dit "en cours" mais que le processus n'existe plus (plantage,
    arrêt forcé, redémarrage), l'état renvoyé est "interrompu".
    """
    suivi = lire_suivi(chemin_dataset)
    if suivi is not None and suivi.get("etat") == "en cours" and not processus_actif(suivi.get("pid")):
        suivi["etat"] = "interrompu"
        suivi["message"] = "Le processus s'est arrêté avant la fin."
    return suivi


def lancer_patching(chemin_dataset, splits: list, noms_formats: list, full_width: bool):
    """
    Lance data_utils.py en arrière-plan et rend la main immédiatement.

    `noms_formats` : noms des formats choisis dans le catalogue (le script
    retrouve leurs paramètres dans config.yaml). Plusieurs formats sont
    patchés en un seul lancement.

    Le processus est détaché de l'application (nouvelle session) : il
    continue si la page est rechargée ou fermée. Sa sortie va dans le journal.

    Pour l'instant le script tourne sur la même machine que l'application, donc
    config.yaml est lu directement. Sur le serveur, il faudra copier ce fichier
    avant le lancement.
    """
    DOSSIER_SUIVI.mkdir(parents=True, exist_ok=True)

    commande = [
        PYTHON_PATCHING, str(SCRIPT_PATCHING),
        "--dataset", str(chemin_dataset),
        "--config", str(CONFIG_FORMATS),
        "--splits", *[s.lower() for s in splits],
        "--formats", *noms_formats,
        "--suivi", str(chemin_suivi(chemin_dataset)),
    ]
    if full_width:
        commande.append("--full-width")

    # Le journal reçoit la sortie normale et les erreurs du script
    with open(chemin_journal(chemin_dataset), "w", encoding="utf-8") as journal:
        processus = subprocess.Popen(
            commande, stdout=journal, stderr=subprocess.STDOUT, start_new_session=True
        )

    # Un thread attend la fin du processus pour que le système le libère
    # proprement (sinon il reste "zombie" et paraît toujours actif)
    threading.Thread(target=processus.wait, daemon=True).start()

    # Suivi initial : le script met plusieurs secondes à démarrer (imports),
    # et il écrasera ce fichier dès qu'il aura son propre état
    ecrire_suivi_local(chemin_dataset, {
        "etat": "en cours",
        "format": "",
        "splits": list(splits),
        "cubes_total": 0,
        "cubes_faits": 0,
        "cube_courant": "",
        "message": "",
        "pid": processus.pid,
        "debut": datetime.now().isoformat(timespec="seconds"),
    })


def annuler_patching(chemin_dataset):
    """
    Arrête le patching en cours et note l'annulation dans le fichier de suivi.

    Le split interrompu n'a pas son CSV à 100 % : il reste donc non patché
    et pourra être relancé (le script repart alors de zéro pour ce split).
    """
    suivi = lire_suivi(chemin_dataset)
    if suivi is None:
        return
    pid = suivi.get("pid")
    if processus_actif(pid):
        # Le processus est chef de sa propre session : on arrête tout son groupe
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    suivi["etat"] = "annule"
    suivi["message"] = "Patching annulé par l'utilisateur."
    ecrire_suivi_local(chemin_dataset, suivi)


def effacer_suivi(chemin_dataset):
    """Supprime le fichier de suivi (ce qui masque le dernier résultat dans la page)."""
    chemin_suivi(chemin_dataset).unlink(missing_ok=True)