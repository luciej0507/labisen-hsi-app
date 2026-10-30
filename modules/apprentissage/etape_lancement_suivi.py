"""
modules/apprentissage/etape_lancement_suivi.py

Étape 4 de la page Apprentissage : lancement et suivi de l'entraînement.
Ce fichier prépare ce que la page affiche : l'état et le choix des GPU, et le
récapitulatif de la configuration validée à l'étape Paramétrage.

Ce module ne contient aucune interface Streamlit : l'affichage est dans la
page 4c_apprentissage.py.
"""

from modules.apprentissage.etape_parametrage import TITRES_BLOCS, TYPES_APPRENTISSAGE

# Titre du bloc de choix du GPU
TITRE_BLOC_GPU = "Choix du GPU (serveur)"


# ---------------------------------------------------------------------------
# GPU
# ---------------------------------------------------------------------------

def lire_gpus() -> list:
    """
    Renvoie l'état des GPU du serveur.

    ATTENTION : DONNÉES FACTICES pour le développement de l'interface.
    À remplacer plus tard par la lecture réelle (par exemple nvidia-smi
    exécuté sur le serveur). La mémoire est exprimée en Go.
    """
    return [
        {"index": 0, "utilisation": 5, "memoire_utilisee": 1.2, "memoire_totale": 24.0},
        {"index": 1, "utilisation": 87, "memoire_utilisee": 19.5, "memoire_totale": 24.0},
        {"index": 2, "utilisation": 0, "memoire_utilisee": 0.4, "memoire_totale": 24.0},
        {"index": 3, "utilisation": 42, "memoire_utilisee": 10.8, "memoire_totale": 24.0},
    ]


def lignes_gpus(gpus: list) -> list:
    """Prépare les lignes du tableau d'état des GPU."""
    return [
        {
            "GPU": f"GPU {g['index']}",
            "Utilisation (%)": g["utilisation"],
            "Mémoire utilisée (Go)": g["memoire_utilisee"],
            "Mémoire totale (Go)": g["memoire_totale"],
        }
        for g in gpus
    ]


def libelle_gpu(gpu: dict) -> str:
    """Renvoie le texte d'un choix de GPU, par exemple "GPU 1 (87 % utilisé)"."""
    return f"GPU {gpu['index']} ({gpu['utilisation']} % utilisé)"


# ---------------------------------------------------------------------------
# Récapitulatif de la configuration
# ---------------------------------------------------------------------------

def formater_valeur(valeur) -> str:
    """Met une valeur en forme pour l'affichage : Oui/Non pour un booléen."""
    if isinstance(valeur, bool):
        return "Oui" if valeur else "Non"
    return str(valeur)


def blocs_recapitulatif(config: dict) -> list:
    """
    Prépare le récapitulatif de la configuration, bloc par bloc.

    Renvoie une liste de (titre, teinte, lignes) dans l'ordre des expanders
    de l'étape Paramétrage, où lignes est une liste de (nom, valeur) déjà
    mises en forme. La teinte est celle du bloc dans la page (bleu, violet,
    turquoise, orange).
    """
    # Libellé lisible du type d'apprentissage (l'inverse de TYPES_APPRENTISSAGE)
    libelles_types = {valeur: nom for nom, valeur in TYPES_APPRENTISSAGE.items()}
    labels = "0 (normaux)" if config["labels_retenus"] == [0] else "Tous"

    return [
        (TITRES_BLOCS["modele"], "bleu", [
            ("Type d'apprentissage", libelles_types[config["type_apprentissage"]]),
            ("Modèle", config["modele"]),
        ]),
        (TITRES_BLOCS["hyperparametres"], "violet", [
            (nom, formater_valeur(valeur))
            for nom, valeur in config["hyperparametres"].items()
        ]),
        (TITRES_BLOCS["generaux"], "turquoise", [
            (nom, formater_valeur(valeur))
            for nom, valeur in config["parametres_generaux"].items()
        ]),
        (TITRES_BLOCS["donnees"], "orange", [
            ("Split", config["split"]),
            ("Format de patches", config["format_patches"]),
            ("Fraction du CSV", f"{config['fraction_csv']} %"),
            ("Labels retenus", labels),
        ]),
    ]