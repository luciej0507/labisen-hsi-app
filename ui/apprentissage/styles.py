"""Styles de la page Apprentissage : couleurs et CSS injectés dans la page.

Chaque conteneur Streamlit créé avec une clé reçoit une classe CSS
"st-key-<clé>" : les règles ci-dessous s'appuient sur ces classes.
"""

import streamlit as st

from ui.apprentissage import etat

# Couleurs des boutons de la frise pour une étape validée.
# Le texte blanc sur ce vert a un contraste de 5,3:1 (WCAG AA : 4,5:1 minimum).
VERT = "#207a46"
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

# Teinte de chaque bloc du paramétrage : (composantes RVB du cadre, couleur du
# titre). Les couleurs des titres ont un contraste d'au moins 4,5:1 sur fond
# blanc, comme le demande le niveau AA des WCAG (critère 1.4.3).
TEINTES = {
    "bleu": ("47, 128, 237", "#1a5fc4"),
    "violet": ("142, 91, 214", "#7440c0"),
    "turquoise": ("20, 184, 166", "#0b6e63"),
    "orange": ("217, 115, 13", "#a8510a"),
    "vert": ("31, 157, 85", "#1a7a45"),
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


def css_tuile_mlflow():
    """Construit le CSS de la tuile MLflow (carte cliquable avec le logo).

    La tuile est un lien HTML de classe "tuile-mlflow". Il ne contient que
    des <span> (des <div> feraient découper le lien par Streamlit) : le CSS
    les transforme en blocs avec "display: block". Les couleurs sont
    semi-transparentes pour fonctionner avec les thèmes clair et sombre.
    """
    return """
<style>
/* Carte cliquable : cadre gris discret, coins arrondis */
a.tuile-mlflow {
    display: block;
    padding: 1rem 1.25rem;
    border: 1px solid rgba(128, 128, 128, 0.35);
    border-radius: 0.75rem;
    text-decoration: none !important;
    color: inherit !important;
    transition: border-color 0.15s, box-shadow 0.15s;
}
/* Au survol : bordure rouge et ombre légère */
a.tuile-mlflow:hover {
    border-color: #c8102e;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.12);
}
/* Logo sur fond blanc pour rester lisible avec le thème sombre */
a.tuile-mlflow img {
    display: block;
    height: 2.5rem;
    padding: 0.25rem 0.5rem;
    margin-bottom: 0.75rem;
    border-radius: 0.5rem;
    background-color: #ffffff;
}
a.tuile-mlflow .tuile-titre {
    display: block;
    font-weight: 700;
    font-size: 1.1rem;
}
a.tuile-mlflow .tuile-texte {
    display: block;
    margin: 0.25rem 0 1rem 0;
    font-size: 0.9rem;
    opacity: 0.7;
}
/* Ligne du bas : "Ouvrir" à gauche, port à droite */
a.tuile-mlflow .tuile-bas {
    display: flex;
    justify-content: space-between;
    align-items: center;
}
a.tuile-mlflow .tuile-ouvrir {
    color: #c8102e;
    font-weight: 600;
}
a.tuile-mlflow .tuile-port {
    font-family: monospace;
    font-size: 0.85rem;
    opacity: 0.6;
}
</style>
"""

def css_cartes_gpu():
    """Construit le CSS des cartes GPU (choix du GPU à l'étape 4).

    Chaque carte est un conteneur de clé "gpu-carte-<n>" (ou "gpu-choisie-<n>"
    quand le GPU est sélectionné), qui reçoit la classe CSS "st-key-...".
    Le donut d'utilisation est un disque dégradé "conic-gradient" percé
    en son centre : --p est le pourcentage et --c la couleur.
    """
    return """
<style>
/* Carte GPU : cadre gris discret */
div[class*="st-key-gpu-carte-"],
div[class*="st-key-gpu-choisie-"] {
    padding: 0.75rem 1rem;
    border-radius: 0.5rem;
    border: 1px solid rgba(128, 128, 128, 0.35);
}
/* Carte du GPU sélectionné : bordure rouge et fond léger */
div[class*="st-key-gpu-choisie-"] {
    border: 2px solid #c8102e;
    background-color: rgba(200, 16, 46, 0.06);
}
/* Ligne du haut : nom du GPU à gauche, état à droite */
.gpu-entete {
    display: flex;
    justify-content: space-between;
    align-items: center;
}
.gpu-nom {
    font-weight: 700;
    font-size: 1.05rem;
}
/* Pastille d'état : texte et bordure colorés (--t texte, --c bordure) */
.gpu-etat {
    padding: 0.05rem 0.55rem;
    border: 1px solid var(--c);
    border-radius: 1rem;
    color: var(--t);
    font-size: 0.8rem;
    font-weight: 600;
}
/* Ligne "Recommandé" (vide pour les autres GPU, pour aligner les cartes) */
.gpu-reco {
    min-height: 1.2rem;
    color: #1a7a45;
    font-size: 0.8rem;
    font-weight: 600;
}
/* Donut : disque dégradé dont le centre est découpé par un masque */
.gpu-donut {
    position: relative;
    width: 5.5rem;
    height: 5.5rem;
    margin: 0.25rem auto;
}
.gpu-donut::before {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: 50%;
    background: conic-gradient(var(--c) calc(var(--p) * 1%), rgba(128, 128, 128, 0.2) 0);
    -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 0.6rem), #000 calc(100% - 0.6rem));
    mask: radial-gradient(farthest-side, transparent calc(100% - 0.6rem), #000 calc(100% - 0.6rem));
}
/* Pourcentage au centre du donut */
.gpu-donut span {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    font-weight: 700;
}
.gpu-legende {
    text-align: center;
    font-size: 0.8rem;
    opacity: 0.7;
    margin-bottom: 0.75rem;
}
/* Ligne de mémoire : libellé à gauche, valeur à droite, sans retour à la ligne */
.gpu-memoire {
    display: flex;
    justify-content: space-between;
    white-space: nowrap;
    font-size: 0.8rem;
    margin-bottom: 0.25rem;
}
/* Barre de mémoire : fond gris, remplissage coloré */
.gpu-barre {
    height: 0.5rem;
    margin-bottom: 0.75rem;
    border-radius: 0.25rem;
    background-color: rgba(128, 128, 128, 0.2);
    overflow: hidden;
}
.gpu-barre div {
    height: 100%;
}
</style>
"""