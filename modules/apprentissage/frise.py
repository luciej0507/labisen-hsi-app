"""
modules/apprentissage/frise.py

Règles de la frise de la page Apprentissage : liste des étapes, étapes
validées et verrouillage des étapes suivantes.

Le parcours est obligatoire : un dataset à l'état Complet, puis le
patching, puis le choix de l'entraînement, puis le récapitulatif.
"""

# Étapes du parcours, dans l'ordre d'affichage de la frise
ETAPES = [
    {"cle": "dataset", "titre": "Dataset"},
    {"cle": "patching", "titre": "Patching"},
    {"cle": "entrainement", "titre": "Entraînement"},
    {"cle": "recapitulatif", "titre": "Récapitulatif"},
]


def etapes_validees(dataset, version) -> list:
    """
    Renvoie une liste de booléens (un par étape) indiquant celles qui
    sont validées.

    - Dataset : validée dès qu'un dataset a été choisi.
    - Patching : validée dès qu'une version de patches a été choisie.
    - Les deux dernières étapes suivront avec leur contenu.
    """
    return [dataset is not None, version is not None, False, False]


def etape_accessible(index: int, validees: list) -> bool:
    """
    Indique si l'étape `index` est accessible.

    La première étape l'est toujours. Les suivantes ne le sont que si
    toutes les étapes précédentes sont validées.
    """
    return all(validees[:index])


def libelle_etape(index: int, validee: bool) -> str:
    """Renvoie le texte du bouton d'une étape, par exemple "1. Dataset"."""
    texte = f"{index + 1}. {ETAPES[index]['titre']}"
    if validee:
        texte += " (validé)"
    return texte