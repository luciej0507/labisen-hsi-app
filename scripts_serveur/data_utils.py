"""
data_utils.py

Patching des cubes HSI (et des photos RGB associées) d'un dataset.

Ce script s'exécute sur le serveur, avec des chemins locaux. L'application
Streamlit le lance par SSH (voir modules/serveur.py) et suit son avancement
grâce à un petit fichier JSON.

Les patches sont rangés dans le dataset lui-même :

    Avoine1/
      Train/  Test/  Val/
      hsi-data-patching/
        HSI/
          patches/{train,test,val}/{format}/{normal,anormal}/
          before_csv/{train,test,val}/{format}/
          csv_for_dataloader/{train,test,val}/{format}/
        RGB/                       même structure

Un split est considéré comme patché pour un format quand le CSV à 100 %
existe dans csv_for_dataloader/{split}/{format}/ : c'est le dernier fichier
écrit (voir generer_csv_dataloader). Il n'y a pas de fiche de préparation.

Exemple de lancement :

    python data_utils.py --dataset /chemin/Avoine1 --splits train test \
        --n-lines 100 --patch-size 100 --stride-lines 100 --stride-cols 80
"""

import argparse
import csv
import json
import os
import re
import shutil
import sys
import traceback
from datetime import datetime

import numpy as np
import pandas as pd
import spectral.io.envi as envi
import torch
from torchvision.io import read_image

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Dossier des patches, à l'intérieur du dataset
NOM_DOSSIER_PATCHING = "hsi-data-patching"

# Splits, écrits en minuscules sur le disque (l'interface affiche Train, Test, Val)
SPLITS = ["train", "test", "val"]

# Le CSV à 100 % de HSI doit être le dernier fichier écrit d'un split :
# HSI passe donc en dernier dans cette liste.
MODALITES = ["RGB", "HSI"]

SOUS_DOSSIERS = ["patches", "before_csv", "csv_for_dataloader"]

# Fractions de données proposées pour l'entraînement (une par fichier CSV)
RATIOS = [0.1, 0.2, 0.4, 0.8, 1.0]

COLONNES_BEFORE_CSV = ["path_dat", "path_npy", "batch_size", "C", "H", "W", "label"]

# Forme d'un nom de format, par exemple w100_h100_sl50_sc80
MOTIF_FORMAT = re.compile(r"^w\d+_h\d+_sl\d+_sc\d+$")


# ---------------------------------------------------------------------------
# Noms et chemins
# ---------------------------------------------------------------------------


def nom_split(split: str) -> str:
    """Renvoie le nom du split tel qu'il est écrit sur le disque (minuscules)."""
    nom = split.lower()
    if nom not in SPLITS:
        raise ValueError(f"Split inconnu : {split} (attendu : train, test ou val)")
    return nom


def nom_format(n_lines, patch_size, stride_lines, stride_cols) -> str:
    """Construit le nom du dossier d'un format, par exemple w100_h100_sl50_sc80."""
    return f"w{n_lines}_h{patch_size}_sl{stride_lines}_sc{stride_cols}"


def chemin_patching(chemin_dataset: str) -> str:
    """Renvoie le dossier hsi-data-patching d'un dataset."""
    return os.path.join(chemin_dataset, NOM_DOSSIER_PATCHING)


def chemin_format(racine, modalite, sous_dossier, split, format_name) -> str:
    """
    Renvoie le dossier d'un format pour une modalité (HSI ou RGB), un type de
    contenu (patches, before_csv, csv_for_dataloader) et un split.
    """
    return os.path.join(racine, modalite, sous_dossier, nom_split(split), format_name)


# ---------------------------------------------------------------------------
# Lecture du dataset (chemins locaux, sans tenir compte de la casse)
# ---------------------------------------------------------------------------


def trouver_nom(chemin_dossier, voulu, accepter_prefixe=False):
    """
    Cherche un nom dans un dossier sans tenir compte de la casse (train = Train).

    Avec `accepter_prefixe`, un nom qui commence par `voulu` est accepté
    s'il n'y a pas de nom exact (HSI-Hybercube pour HSI).
    Renvoie le vrai nom, ou None s'il n'existe pas.
    """
    if not os.path.isdir(chemin_dossier):
        return None
    noms = os.listdir(chemin_dossier)
    for nom in noms:
        if nom.lower() == voulu.lower():
            return nom
    if accepter_prefixe:
        for nom in sorted(noms):
            if nom.lower().startswith(voulu.lower()):
                return nom
    return None


def resoudre(base, sous_chemin):
    """
    Descend dans `sous_chemin` (ex : "train/Annotation/PNG") à partir de `base`.
    Renvoie le vrai chemin, ou None si un des dossiers n'existe pas.
    """
    chemin = base
    for partie in sous_chemin.split("/"):
        reel = trouver_nom(chemin, partie, accepter_prefixe=(partie.lower() == "hsi"))
        if reel is None:
            return None
        chemin = os.path.join(chemin, reel)
    return chemin


def lister_cubes(chemin_dataset, split):
    """
    Liste les cubes d'un split (un cube = un fichier .bil dans HSI/).
    Renvoie les noms sans extension, triés. Liste vide si le split n'existe pas.
    """
    dossier_hsi = resoudre(chemin_dataset, f"{split}/HSI")
    if dossier_hsi is None:
        return []
    return sorted(
        nom[:-4] for nom in os.listdir(dossier_hsi) if nom.lower().endswith(".bil")
    )


def chercher_fichier(dossier, nom_fichier):
    """Renvoie le chemin d'un fichier d'un dossier (casse ignorée), ou None."""
    if dossier is None:
        return None
    reel = trouver_nom(dossier, nom_fichier)
    if reel is None:
        return None
    return os.path.join(dossier, reel)


def chemins_cube(chemin_dataset, split, nom_cube):
    """
    Renvoie les chemins des trois fichiers d'un cube : l'en-tête (.bil.hdr),
    la photo RGB et le masque d'annotation.

    Le masque est cherché dans Annotation/PNG, puis directement dans
    Annotation (règle temporaire, comme dans datasets.py).
    Lève FileNotFoundError si un des fichiers est introuvable.
    """
    hdr = chercher_fichier(resoudre(chemin_dataset, f"{split}/HSI"), f"{nom_cube}.bil.hdr")
    rgb = chercher_fichier(resoudre(chemin_dataset, f"{split}/RGB"), f"{nom_cube}.png")
    masque = None
    for sous_chemin in ("Annotation/PNG", "Annotation"):
        masque = chercher_fichier(
            resoudre(chemin_dataset, f"{split}/{sous_chemin}"), f"{nom_cube}.png"
        )
        if masque is not None:
            break

    for description, chemin in (("en-tête .bil.hdr", hdr), ("photo RGB", rgb), ("masque", masque)):
        if chemin is None:
            raise FileNotFoundError(f"{description} introuvable pour le cube {nom_cube} (split {split})")
    return {"hdr": hdr, "rgb": rgb, "masque": masque}


def get_cube(hdrfile):
    """Lit un cube HSI : renvoie le tableau (H, W, C) et la liste des longueurs d'onde."""
    img = envi.open(hdrfile)
    info = envi.read_envi_header(hdrfile)

    # Toujours convertir en numpy array
    img = img.asarray()

    # Appliquer le scale si présent
    if "reflectance scale factor" in info:
        img = img / float(info["reflectance scale factor"])

    return img, [float(v) for v in info['wavelength']]


def largeur_commune(chemin_dataset, cubes_par_split):
    """
    Renvoie la largeur (nombre de colonnes) commune à tous les cubes.

    Sert au mode largeur complète, où le nom du format contient la largeur.
    Lève ValueError si les cubes n'ont pas tous la même largeur.
    """
    largeurs = set()
    for split, cubes in cubes_par_split.items():
        for nom_cube in cubes:
            hdr = chemins_cube(chemin_dataset, split, nom_cube)["hdr"]
            largeurs.add(envi.open(hdr).ncols)
    if len(largeurs) != 1:
        raise ValueError(
            f"Les cubes n'ont pas tous la même largeur ({sorted(largeurs)}) : "
            "le mode largeur complète est impossible"
        )
    return largeurs.pop()


# ---------------------------------------------------------------------------
# Extraction des patches
# ---------------------------------------------------------------------------


def extract_patches_HSI(cube, mask=None, n_lines=100, patch_size=100, stride_lines=100, stride_cols=100, full_width=False):
    """Découpe un cube HSI (H, W, C) en patches, avec un label par patch si un masque est donné."""
    H, W, C = cube.shape

    if full_width:
        patch_size = W
        stride_cols = W

    # ----------- PATCHES CUBE -----------
    x = cube.permute(2, 0, 1).unsqueeze(0)  # (1, C, H, W)
    unfolded = torch.nn.functional.unfold(
        x,
        kernel_size=(n_lines, patch_size),
        stride=(stride_lines, stride_cols)
    )
    N = unfolded.shape[-1]
    patches = unfolded.transpose(1, 2).reshape(N, C, n_lines, patch_size)

    # ----------- OPTIONAL: PATCHES MASK & LABELS -----------
    if mask is not None:
        m = mask.unsqueeze(0).unsqueeze(0).float()
        mask_unfolded = torch.nn.functional.unfold(
            m,
            kernel_size=(n_lines, patch_size),
            stride=(stride_lines, stride_cols)
        )
        mask_patches = mask_unfolded.squeeze(0).transpose(0, 1).reshape(N, n_lines, patch_size)

        labels = (mask_patches == 255).any(dim=(1, 2)).int().tolist()
        return patches, labels

    return patches


def extract_patches_RGB(image, mask=None, n_lines=100, patch_size=100, stride_lines=100, stride_cols=100, full_width=False):
    """
    Découpe une photo RGB en patches.

    image: torch.Tensor de forme (3, H, W), lue avec torchvision.io.read_image
    mask: torch.Tensor de forme (H, W) ou None
    """
    if image.shape[0] != 3:
        raise ValueError(f"Expected image shape (3, H, W), but got {image.shape}")

    image = image.float()
    C, H, W = image.shape

    if full_width:
        patch_size = W
        stride_cols = W

    # Convert to (1, C, H, W)
    x = image.unsqueeze(0).contiguous()

    # Vérifie que le patch tient dans l'image
    if H < n_lines or W < patch_size:
        raise ValueError(f"Patch size ({n_lines}, {patch_size}) is too big for image size ({H}, {W})")

    # Extraction des patches
    unfolded = torch.nn.functional.unfold(
        x,
        kernel_size=(n_lines, patch_size),
        stride=(stride_lines, stride_cols)
    )
    N = unfolded.shape[-1]
    patches = unfolded.transpose(1, 2).reshape(N, C, n_lines, patch_size)

    # ----------- OPTIONAL: PATCHES MASK & LABELS -----------
    if mask is not None:
        if mask.shape != (H, W):
            raise ValueError(f"Mask shape must be ({H}, {W}), but got {mask.shape}")
        m = mask.unsqueeze(0).unsqueeze(0).float()
        mask_unfolded = torch.nn.functional.unfold(
            m,
            kernel_size=(n_lines, patch_size),
            stride=(stride_lines, stride_cols)
        )
        mask_patches = mask_unfolded.squeeze(0).transpose(0, 1).reshape(N, n_lines, patch_size)

        # Critère : au moins un pixel avec la valeur 255
        labels = (mask_patches == 255).any(dim=(1, 2)).int().tolist()
        return patches, labels

    return patches


# ---------------------------------------------------------------------------
# Écriture des patches et des CSV
# ---------------------------------------------------------------------------


def nettoyer_split_format(racine, split, format_name):
    """
    Efface puis recrée les dossiers d'un split pour un format.

    Appelée avant chaque patching : relancer un split repart de zéro, sans
    doublons dans les CSV. Le CSV à 100 % disparaît aussi, donc le split
    n'est plus considéré comme patché tant que le travail n'est pas fini.
    """
    # Garde-fou : on n'efface jamais un dossier dont le nom n'a pas la forme d'un format
    if not MOTIF_FORMAT.match(format_name):
        raise ValueError(f"Nom de format invalide : {format_name}")

    for modalite in MODALITES:
        for sous_dossier in SOUS_DOSSIERS:
            dossier = chemin_format(racine, modalite, sous_dossier, split, format_name)
            shutil.rmtree(dossier, ignore_errors=True)
            os.makedirs(dossier)


def sauvegarder_patches(patches, labels, racine, modalite, split, format_name, nom_cube):
    """
    Enregistre les patches d'un cube pour une modalité, séparés en normal
    (label 0) et anormal (label 1), et ajoute une ligne par groupe dans le
    CSV before_csv.

    Les chemins écrits dans le CSV sont relatifs au dossier hsi-data-patching,
    pour rester valables si le dataset est déplacé.
    """
    chemin_csv = os.path.join(
        chemin_format(racine, modalite, "before_csv", split, format_name),
        f"{nom_split(split)}_{format_name}.csv",
    )

    for valeur_label, sous_dossier in ((0, "normal"), (1, "anormal")):
        liste = [patch for patch, label in zip(patches, labels) if label == valeur_label]
        if not liste:
            continue

        tableau = torch.stack(liste).cpu().numpy()
        dossier = os.path.join(
            chemin_format(racine, modalite, "patches", split, format_name), sous_dossier
        )
        os.makedirs(dossier, exist_ok=True)
        chemin_dat = os.path.join(dossier, f"{nom_cube}_patches.dat")
        chemin_npy = os.path.join(dossier, f"{nom_cube}_shape.npy")

        # Les patches sont écrits dans un fichier .dat, la forme dans un .npy
        memmap = np.memmap(chemin_dat, dtype="float32", mode="w+", shape=tableau.shape)
        memmap[:] = tableau[:]
        memmap.flush()
        np.save(chemin_npy, tableau.shape)

        # Une ligne par fichier .dat dans le CSV
        B, C, H, W = tableau.shape
        ecrire_entete = not os.path.exists(chemin_csv)
        with open(chemin_csv, mode="a", newline="") as fichier:
            ecrivain = csv.DictWriter(fichier, fieldnames=COLONNES_BEFORE_CSV)
            if ecrire_entete:
                ecrivain.writeheader()
            ecrivain.writerow({
                "path_dat": os.path.relpath(chemin_dat, racine),
                "path_npy": os.path.relpath(chemin_npy, racine),
                "batch_size": B,
                "C": C,
                "H": H,
                "W": W,
                "label": valeur_label,
            })


def generer_csv_dataloader(racine, split, format_name):
    """
    Génère les CSV utilisés par le dataloader, pour un split et un format.

    Une ligne par patch, puis un fichier par fraction de données
    (10 %, 20 %, 40 %, 80 %, 100 %), tirée au hasard dans chaque label.

    Le CSV à 100 % de HSI est le dernier fichier écrit : sa présence indique
    que le split est entièrement patché pour ce format.
    """
    split = nom_split(split)

    for modalite in MODALITES:
        chemin_before = os.path.join(
            chemin_format(racine, modalite, "before_csv", split, format_name),
            f"{split}_{format_name}.csv",
        )
        if not os.path.exists(chemin_before):
            raise FileNotFoundError(
                f"Aucun patch produit pour le split {split} au format {format_name} "
                "(la fenêtre est peut-être plus grande que les cubes)"
            )
        dossier_final = chemin_format(racine, modalite, "csv_for_dataloader", split, format_name)

        # Une ligne par patch : on déplie les groupes de before_csv
        df = pd.read_csv(chemin_before)
        lignes = []
        for _, ligne in df.iterrows():
            for index in range(int(ligne["batch_size"])):
                lignes.append({
                    "path_dat": ligne["path_dat"],
                    "path_npy": ligne["path_npy"],
                    "index": index,
                    "label": ligne["label"],
                })
        complet = pd.DataFrame(lignes)
        complet.to_csv(os.path.join(dossier_final, f"{split}_{format_name}.csv"), index=False)

        # Un fichier par fraction, en gardant la même proportion dans chaque label
        for ratio in RATIOS:
            extraits = []
            for label in complet["label"].unique():
                par_label = complet[complet["label"] == label]
                extraits.append(par_label.sample(n=int(len(par_label) * ratio), random_state=42))
            nom_fichier = f"{round(ratio * 100)}%_{split}_{format_name}.csv"
            pd.concat(extraits).to_csv(os.path.join(dossier_final, nom_fichier), index=False)


# ---------------------------------------------------------------------------
# Patching d'un cube et d'un dataset
# ---------------------------------------------------------------------------


def patcher_cube(chemin_dataset, split, nom_cube, parametres, format_name):
    """
    Découpe un cube (HSI et RGB) en patches et les enregistre.

    `parametres` : dictionnaire avec n_lines, patch_size, stride_lines,
    stride_cols et full_width (patch_size et stride_cols valent None en
    largeur complète).

    Renvoie le nombre de patches créés (0 si la fenêtre est plus grande
    que le cube : le cube est alors ignoré).
    """
    racine = chemin_patching(chemin_dataset)
    chemins = chemins_cube(chemin_dataset, split, nom_cube)
    full_width = parametres["full_width"]

    cube, _ = get_cube(chemins["hdr"])
    cube = torch.tensor(cube, dtype=torch.float32)  # (H, W, C)
    hauteur, largeur = cube.shape[0], cube.shape[1]

    # Cube plus petit que la fenêtre : aucun patch possible
    taille = largeur if full_width else parametres["patch_size"]
    if hauteur < parametres["n_lines"] or largeur < taille:
        print(f"Cube {nom_cube} ignoré : plus petit que la fenêtre", flush=True)
        return 0

    rgb = read_image(chemins["rgb"])
    mask = read_image(chemins["masque"])[0]  # (H, W), un seul canal

    options = {
        "n_lines": parametres["n_lines"],
        "patch_size": parametres["patch_size"],
        "stride_lines": parametres["stride_lines"],
        "stride_cols": parametres["stride_cols"],
        "full_width": full_width,
    }
    patches_hsi, labels_hsi = extract_patches_HSI(cube, mask=mask, **options)
    patches_rgb, labels_rgb = extract_patches_RGB(rgb, mask=mask, **options)

    sauvegarder_patches(patches_hsi, labels_hsi, racine, "HSI", split, format_name, nom_cube)
    sauvegarder_patches(patches_rgb, labels_rgb, racine, "RGB", split, format_name, nom_cube)
    return len(labels_hsi)


def maintenant() -> str:
    """Renvoie l'heure actuelle au format ISO, sans les fractions de seconde."""
    return datetime.now().isoformat(timespec="seconds")


def ecrire_suivi(fichier_suivi, suivi):
    """
    Écrit l'état d'avancement du job dans un fichier JSON lu par l'application.

    Ce n'est pas une preuve de complétude (c'est le CSV à 100 % qui l'est) :
    ce fichier sert seulement à afficher l'avancement. Il est écrit dans un
    fichier temporaire puis renommé, pour qu'il ne soit jamais lu à moitié.
    """
    if fichier_suivi is None:
        return
    suivi["maj"] = maintenant()
    os.makedirs(os.path.dirname(fichier_suivi) or ".", exist_ok=True)
    temporaire = fichier_suivi + ".tmp"
    with open(temporaire, "w", encoding="utf-8") as fichier:
        json.dump(suivi, fichier, ensure_ascii=False)
    os.replace(temporaire, fichier_suivi)


def patcher_dataset(chemin_dataset, splits, parametres, fichier_suivi=None):
    """
    Patche tous les cubes des splits choisis, au format demandé.

    Pour chaque split : on repart de zéro, on patche chaque cube, puis on
    génère les CSV du dataloader. L'avancement est écrit dans `fichier_suivi`
    (état : en cours, termine ou erreur). Toute erreur est inscrite dans ce
    fichier puis relancée.
    """
    suivi = {
        "etat": "en cours",
        "format": "",
        "splits": list(splits),
        "cubes_total": 0,
        "cubes_faits": 0,
        "cube_courant": "",
        "message": "",
        "pid": os.getpid(),  # permet à l'application de savoir si le job tourne encore
        "debut": maintenant(),
    }
    ecrire_suivi(fichier_suivi, suivi)

    try:
        splits = [nom_split(s) for s in splits]
        racine = chemin_patching(chemin_dataset)

        cubes_par_split = {s: lister_cubes(chemin_dataset, s) for s in splits}
        total = sum(len(cubes) for cubes in cubes_par_split.values())
        if total == 0:
            raise ValueError("Aucun cube trouvé dans les splits choisis")

        # Nom du format : en largeur complète, il contient la largeur des cubes
        if parametres["full_width"]:
            largeur = largeur_commune(chemin_dataset, cubes_par_split)
            format_name = nom_format(
                parametres["n_lines"], largeur, parametres["stride_lines"], largeur
            )
        else:
            format_name = nom_format(
                parametres["n_lines"], parametres["patch_size"],
                parametres["stride_lines"], parametres["stride_cols"],
            )

        suivi["format"] = format_name
        suivi["cubes_total"] = total
        ecrire_suivi(fichier_suivi, suivi)

        for split in splits:
            nettoyer_split_format(racine, split, format_name)
            for nom_cube in cubes_par_split[split]:
                suivi["cube_courant"] = f"{nom_cube} ({split})"
                ecrire_suivi(fichier_suivi, suivi)
                print(f"Patching de {nom_cube} (split {split})", flush=True)

                patcher_cube(chemin_dataset, split, nom_cube, parametres, format_name)

                suivi["cubes_faits"] += 1
                ecrire_suivi(fichier_suivi, suivi)

            # Dernière étape du split : après elle, le split est patché
            generer_csv_dataloader(racine, split, format_name)
            print(f"Split {split} terminé", flush=True)

        suivi["etat"] = "termine"
        suivi["cube_courant"] = ""
        suivi["message"] = f"{total} cube(s) traité(s), format {format_name}"
        suivi["fin"] = maintenant()
        ecrire_suivi(fichier_suivi, suivi)

    except Exception as erreur:
        suivi["etat"] = "erreur"
        suivi["message"] = str(erreur)
        suivi["fin"] = maintenant()
        ecrire_suivi(fichier_suivi, suivi)
        raise


# ---------------------------------------------------------------------------
# Lancement en ligne de commande
# ---------------------------------------------------------------------------


def lire_arguments():
    """Lit les arguments de la ligne de commande."""
    parseur = argparse.ArgumentParser(description="Patching des cubes HSI d'un dataset")
    parseur.add_argument("--dataset", required=True, help="Chemin du dataset sur le serveur")
    parseur.add_argument("--splits", nargs="+", default=SPLITS, help="Splits à patcher (train test val)")
    parseur.add_argument("--n-lines", type=int, required=True, help="Nombre de lignes d'un patch")
    parseur.add_argument("--patch-size", type=int, help="Taille d'un patch en colonnes")
    parseur.add_argument("--stride-lines", type=int, required=True, help="Pas en lignes")
    parseur.add_argument("--stride-cols", type=int, help="Pas en colonnes")
    parseur.add_argument("--full-width", action="store_true", help="Patches sur toute la largeur du cube")
    parseur.add_argument("--suivi", help="Fichier JSON où écrire l'avancement")
    arguments = parseur.parse_args()

    # Sans largeur complète, la taille et le pas en colonnes sont obligatoires
    if not arguments.full_width and (arguments.patch_size is None or arguments.stride_cols is None):
        parseur.error("--patch-size et --stride-cols sont obligatoires sans --full-width")
    return arguments


def main():
    """Point d'entrée : lit les arguments puis lance le patching."""
    arguments = lire_arguments()
    parametres = {
        "n_lines": arguments.n_lines,
        "patch_size": None if arguments.full_width else arguments.patch_size,
        "stride_lines": arguments.stride_lines,
        "stride_cols": None if arguments.full_width else arguments.stride_cols,
        "full_width": arguments.full_width,
    }
    try:
        patcher_dataset(arguments.dataset, arguments.splits, parametres, arguments.suivi)
    except Exception:
        # L'erreur est déjà dans le fichier de suivi : on l'affiche aussi dans le log
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()