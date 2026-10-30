"""
modules/apprentissage/etape_parametrage.py

Choix proposés à l'étape Paramétrage de la page Apprentissage : type
d'apprentissage, modèle et hyperparamètres, split et fraction du CSV.

Ce module ne contient aucune interface Streamlit : uniquement des listes de
choix, des valeurs par défaut et de petites fonctions de mise en forme.
"""

import re

# Format de patches mis en premier dans le menu : "w1" (mais pas "w100", "w200"...)
MOTIF_FORMAT_PRIORITAIRE = re.compile(r"(?<![A-Za-z0-9])w1(?![0-9])")


def trier_formats(noms: list) -> list:
    """
    Renvoie les formats de patches avec le format w1 en premier.

    Les autres formats gardent leur ordre d'origine (le tri est stable).
    """
    return sorted(noms, key=lambda nom: not MOTIF_FORMAT_PRIORITAIRE.search(nom))


# Types d'apprentissage : libellé affiché -> valeur enregistrée
TYPES_APPRENTISSAGE = {
    "Non supervisé": "non_supervise",
    "Supervisé": "supervise",
}
TYPE_PAR_DEFAUT = "Non supervisé"

# Splits proposés pour l'entraînement (train présélectionné)
SPLITS = ["train", "val", "test"]
SPLIT_PAR_DEFAUT = "train"

# Fractions du CSV proposées, en pourcentage
FRACTIONS = [10, 20, 40, 60, 80, 100]
FRACTION_PAR_DEFAUT = 10

# Hyperparamètres propres à chaque modèle anomalib. Pour ajouter un modèle,
# il suffit d'ajouter une entrée à ce dictionnaire (et sa documentation dans
# DOCUMENTATIONS plus bas).
# Types possibles : "choix", "booleen", "entier", "decimal".
# "aide" est le texte de l'infobulle affichée à côté du champ.
MODELES = {
    "FastFlow": [
        {
            "cle": "backbone", "libelle": "backbone", "type": "choix",
            "options": ["resnet18", "wide_resnet50_2"],
            "defaut": "resnet18",
            "aide": "Réseau de neurones convolutif qui extrait les caractéristiques "
                    "des patches. wide_resnet50_2 est plus profond que resnet18 : "
                    "souvent plus précis, mais plus lent et plus gourmand en mémoire.",
        },
        {
            "cle": "pre_trained", "libelle": "pre_trained",
            "type": "booleen", "defaut": True,
            "aide": "Utilise les poids du backbone pré-entraînés (sur ImageNet) "
                    "plutôt qu'une initialisation aléatoire.",
        },
        {
            "cle": "flow_steps", "libelle": "flow_steps",
            "type": "entier", "min": 1, "max": 32, "pas": 1, "defaut": 8,
            "aide": "Nombre d'étapes du flux de normalisation. Plus il est élevé, "
                    "plus le modèle est expressif, mais plus l'entraînement est lent.",
        },
        {
            "cle": "hidden_ratio", "libelle": "hidden_ratio",
            "type": "decimal", "min": 0.1, "max": 4.0, "pas": 0.1, "defaut": 1.0,
            "aide": "Rapport utilisé pour calculer le nombre de canaux des variables "
                    "cachées du flux. Une valeur plus grande donne un modèle plus gros.",
        },
        {
            "cle": "conv3x3_only", "libelle": "conv3x3_only",
            "type": "booleen", "defaut": False,
            "aide": "N'utilise que des convolutions 3x3 dans le flux "
                    "(modèle plus léger).",
        },
    ],
}
MODELE_PAR_DEFAUT = "FastFlow"

# Paramètres généraux de l'entraînement, communs à tous les modèles
# (ils relèvent du chargement des données et de l'entraînement, pas du modèle)
PARAMETRES_GENERAUX = [
    {
        "cle": "batch_size", "libelle": "batch_size",
        "type": "entier", "min": 1, "max": 256, "pas": 1, "defaut": 128,
        "aide": "Nombre de patches traités ensemble à chaque étape d'entraînement. "
                "Plus il est grand, plus la mémoire GPU utilisée augmente.",
    },
    {
        "cle": "epochs", "libelle": "epochs",
        "type": "entier", "min": 1, "max": 1000, "pas": 1, "defaut": 50,
        "aide": "Nombre de passages complets sur les données d'entraînement.",
    },
    {
        "cle": "num_workers", "libelle": "num_workers",
        "type": "entier", "min": 0, "max": 32, "pas": 1, "defaut": 4,
        "aide": "Nombre de processus qui chargent les données en parallèle. "
                "Plus il est élevé, plus le chargement est rapide, jusqu'à "
                "saturer le processeur.",
    },
    {
        "cle": "validation", "libelle": "validation",
        "type": "booleen", "defaut": False,
        "aide": "Si activée, des métriques sont calculées pendant l'entraînement "
                "sur le split de validation. Désactivée, l'entraînement est plus rapide.",
    },
]

# Documentation de chaque modèle, issue d'anomalib (en anglais), affichée en
# Markdown dans le bloc "Documentation du modèle"
DOCUMENTATIONS = {
    "FastFlow": """\
The FastFlow model uses normalizing flows to transform feature distributions from a
pre-trained CNN backbone into a simpler form that can be efficiently modeled for
anomaly detection.

**Args**

- `backbone` (str): Backbone CNN network architecture. Available options are
  `"resnet18"`, `"wide_resnet50_2"`, etc. Defaults to `"resnet18"`.
- `pre_trained` (bool, optional): Whether to use pre-trained backbone weights.
  Defaults to `True`.
- `flow_steps` (int, optional): Number of steps in the normalizing flow.
  Defaults to `8`.
- `conv3x3_only` (bool, optional): Whether to use only 3x3 convolutions in the
  FastFlow model. Defaults to `False`.
- `hidden_ratio` (float, optional): Ratio used to calculate hidden variable
  channels. Defaults to `1.0`.
- `pre_processor` (PreProcessor | bool, optional): Pre-processor to use for
  input data. Defaults to `True`.
- `post_processor` (PostProcessor | bool, optional): Post-processor to use for
  model outputs. Defaults to `True`.
- `evaluator` (Evaluator | bool, optional): Evaluator to compute metrics.
  Defaults to `True`.
- `visualizer` (Visualizer | bool, optional): Visualizer for model outputs.
  Defaults to `True`.
""",
}


def message_labels(type_apprentissage: str) -> str:
    """Indique quels labels du CSV sont retenus selon le type d'apprentissage."""
    if type_apprentissage == "non_supervise":
        return "Apprentissage non supervisé : seules les images de label 0 (normales) sont retenues dans le CSV."
    return "Apprentissage supervisé : tous les labels du CSV sont utilisés."


# ---------------------------------------------------------------------------
# Configuration finale
# ---------------------------------------------------------------------------

def construire_config(type_apprentissage, modele, hyperparametres, parametres_generaux,
                      split, format_patches, fraction) -> dict:
    """
    Regroupe tous les choix du paramétrage dans un seul dictionnaire.

    Ce dictionnaire sera enregistré dans MLflow au lancement (paramètres et
    fichier config.json en artefact). Le GPU n'en fait pas partie : il est
    choisi à l'étape de lancement.
    """
    return {
        "type_apprentissage": type_apprentissage,
        "modele": modele,
        "hyperparametres": hyperparametres,
        "parametres_generaux": parametres_generaux,
        "split": split,
        "format_patches": format_patches,
        "fraction_csv": fraction,
        # En non supervisé, seuls les labels 0 sont gardés ; None = tous
        "labels_retenus": [0] if type_apprentissage == "non_supervise" else None,
    }


# Titres des blocs du paramétrage : utilisés par les expanders et par le
# récapitulatif de l'étape 4, pour qu'ils restent identiques
TITRES_BLOCS = {
    "modele": "1. Approche et modèle",
    "hyperparametres": "2. Hyperparamètres du modèle",
    "generaux": "3. Paramètres généraux",
    "donnees": "4. Données d'entraînement",
}