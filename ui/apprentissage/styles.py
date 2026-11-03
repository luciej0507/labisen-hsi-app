"""Styles de la page Apprentissage : couleurs et CSS injectés dans la page.

Chaque conteneur Streamlit créé avec une clé reçoit une classe CSS
"st-key-<clé>" : les règles ci-dessous s'appuient sur ces classes.
"""

import streamlit as st

from ui.apprentissage import etat

# Couleurs des boutons de la frise pour une étape validée
VERT = "#2e9e5b"
VERT_FONCE = "#1b6b3a"

# Style des cartes du choix de dataset (couleurs semi-transparentes pour les
# thèmes clair et sombre)
STYLE_CARTES = """
<style>
/* Toutes les cartes : cadre gris discret */
div[class*="st-key-carte-"] {
    padding: 0.75rem 1rem;
    border-radius: 0.5rem;
    border: 1px solid rgba(128, 128, 128, 0.35);
}
/* Carte sélectionnée ou validée : bordure marquée et fond léger */
div[class*="st-key-carte-selectionnee-"] {
    border: 2px solid #c8102e;
    background-color: rgba(200, 16, 46, 0.06);
}
/* Bandeau d'en-tête : espacement, coins arrondis et fond vert (état Complet) */
div[class*="st-key-entete-green-"] {
    padding: 0.5rem 0.75rem;
    border-radius: 0.5rem;
    background-color: rgba(33, 195, 84, 0.15);
}
</style>
"""

# Teinte de chaque bloc du paramétrage : (composantes RVB, couleur du titre).
# Les couleurs de fond sont semi-transparentes pour les thèmes clair et sombre.
TEINTES = {
    "bleu": ("47, 128, 237", "#2f80ed"),
    "violet": ("142, 91, 214", "#8e5bd6"),
    "turquoise": ("20, 184, 166", "#14b8a6"),
    "orange": ("217, 115, 13", "#d9730d"),
    "vert": ("31, 157, 85", "#1f9d55"),
}


def css_etapes_validees(validees):
    """Construit le CSS qui colore en vert les boutons des étapes validées.

    Streamlit ne propose pas de bouton vert : on cible chaque bouton par sa
    clé (classe st-key-frise_N). Une étape validée ET active reçoit en plus
    une bordure plus marquée pour se distinguer des autres étapes vertes.
    """
    regles = ""
    for index, validee in enumerate(validees):
        if not validee:
            continue
        actif = st.session_state[etat.ETAPE] == index
        bordure = f"3px solid {VERT_FONCE}" if actif else f"1px solid {VERT}"
        regles += (
            f".st-key-frise_{index} button {{"
            f" background-color: {VERT}; color: white; border: {bordure}; }}"
            f".st-key-frise_{index} button:hover {{"
            f" background-color: {VERT_FONCE}; color: white; }}"
        )
    return regles


def css_blocs_parametrage():
    """Construit le CSS qui colore les expanders du paramétrage.

    Chaque expander est placé dans un conteneur de clé "bloc-<teinte>" qui
    reçoit la classe CSS "st-key-bloc-<teinte>". On colore ensuite le cadre
    de l'expander (details) et le texte de son titre (summary).
    Les teintes sont repérées par préfixe : "bloc-bleu" et
    "bloc-bleu-documentation" partagent donc la même couleur.
    """
    regles = ""
    for nom, (rvb, couleur) in TEINTES.items():
        bloc = f'div[class*="st-key-bloc-{nom}"]'
        regles += (
            # Cadre coloré de l'expander (sans fond)
            f"{bloc} details {{ border: 1px solid rgba({rvb}, 0.45); }}"
            # Titre (et flèche d'ouverture) en couleur et en gras
            f"{bloc} summary, {bloc} summary * {{"
            f" color: {couleur}; font-weight: 600; }}"
        )
    return f"<style>{regles}</style>"


def css_cartes_recapitulatif():
    """Construit le CSS des sections du récapitulatif.

    Chaque section est un conteneur de clé "recap-<teinte>" qui reçoit la
    classe CSS "st-key-recap-<teinte>". Elle est repérée par une barre colorée
    sur son bord gauche, de la même couleur que son titre.
    """
    regles = ""
    for nom, (rvb, couleur) in TEINTES.items():
        regles += (
            f'div[class*="st-key-recap-{nom}"] {{'
            f" border-left: 4px solid {couleur}; padding-left: 0.75rem; }}"
        )
    return f"<style>{regles}</style>"
