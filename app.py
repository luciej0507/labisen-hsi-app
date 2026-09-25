"""
Page d'accueil de l'application SpectraVision (ISEN / LabISEN).

C'est le fichier "point d'entrée" de l'appli Streamlit multipage :
il est affiché par défaut au lancement, avant tout autre onglet.
"""

import streamlit as st

from modules.auth import is_logged_in
from ui.topnav import render_footer, render_topnav

# Doit être le premier appel Streamlit de la page.
st.set_page_config(page_title="SpectraVision", layout="wide")

# En-tête : logos, nom de l'appli, menu et bouton de connexion.
render_topnav("Accueil")

# --- Introduction ---
st.header("Bienvenue !")
st.write(
    "Développée par le **LabISEN**, cette application permet aux utilisateurs "
    "autorisés de gérer les jeux de données d'imagerie hyperspectrale : "
    "consultation, vérification et préparation."
)

# --- Trois cartes : (icône Material, titre, description) ---
CARTES = [
    (
        ":material/database:",
        "Consulter les bases",
        "Parcourez les bases de données disponibles sur le serveur.",
    ),
    (
        ":material/fact_check:",
        "Vérifier la conformité",
        "Contrôlez les jeux de données : cubes HSI, images RGB et annotations.",
    ),
    (
        ":material/tune:",
        "Préparer les données",
        "Préparez vos données pour l'entraînement et l'inférence de modèles.",
    ),
]

# Une colonne par carte.
for colonne, (icone, titre, description) in zip(st.columns(3), CARTES):
    with colonne:
        with st.container(border=True):
            st.markdown(f"#### {icone} {titre}")
            st.write(description)

# --- Boutons d'action ---
# Le bouton "Se connecter" n'apparaît que si personne n'est connecté.
col_mode_emploi, col_connexion, _ = st.columns([1, 1, 3])

with col_mode_emploi:
    if st.button("Lire le mode d'emploi", width="stretch"):
        st.switch_page("pages/1_mode_emploi.py")

if not is_logged_in():
    with col_connexion:
        if st.button("Se connecter", type="primary", width="stretch"):
            st.switch_page("pages/2_connexion.py")

# --- Pied de page : logos et version ---
render_footer()