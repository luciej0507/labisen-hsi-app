"""
modules/apprentissage/formats.py

Mises en forme du texte affiché dans la page Apprentissage : nombres,
nombres par split et dates.

Ces fonctions ne dépendent de rien d'autre dans le projet : elles peuvent
être réutilisées par les autres pages.
"""

from datetime import datetime


def formater_nombre(nombre: int) -> str:
    """Affiche un entier avec un espace comme séparateur de milliers."""
    return f"{nombre:,}".replace(",", " ")


def formater_splits(nombres_par_split: dict) -> str:
    """
    Met en forme un nombre par split.

    Exemple : {"Train": 1200, "Test": 300} devient "Train 1 200, Test 300".
    """
    return ", ".join(
        f"{nom} {formater_nombre(nombre)}" for nom, nombre in nombres_par_split.items()
    )


def formater_date(date_iso) -> str:
    """Transforme une date ISO (2026-10-16T11:30:00) en 16/10/2026 11:30."""
    try:
        return datetime.fromisoformat(date_iso).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return "inconnue"