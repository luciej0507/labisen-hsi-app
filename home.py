"""
Home.py — Page d'accueil de l'application ISEN / LabISEN HSI.

C'est le fichier "point d'entrée" de l'appli Streamlit multipage :
il est affiché par défaut au lancement, avant tout autre onglet.
"""

from pathlib import Path
import streamlit as st

# --- Configuration générale de la page (doit être en tout premier appel Streamlit) ---
st.set_page_config(
    page_title="ISEN HSI App",
    # page_icon="🌾",
    layout="wide",
)

from modules.topnav import render_topnav
render_topnav()



# --- Logo ISEN / LabISEN ---
# Placez le fichier logo dans assets/isen_logo.png à la racine du projet.
LOGO_PATH = Path(__file__).parent / "assets" / "isen_logo.jpg"

col_logo, col_title = st.columns([1, 4])

with col_logo:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=150)
    else:
        # Ne bloque pas l'affichage si le logo n'a pas encore été déposé
        st.warning("Logo non trouvé : ajoutez-le dans assets/isen_logo.jpg")

with col_title:
    st.title("Application HSI — ISEN / LabISEN")

st.divider()

# --- Texte de présentation (US-01 : 2 à 3 paragraphes) ---
st.markdown(
    """
    ### Bienvenue !

    Cette application a été développée par le **LabISEN**.

    Elle permet aux utilisateurs autorisés de consulter les bases de données disponibles
    sur le serveur, de vérifier la conformité des jeux de données (cubes HSI,
    images RGB, annotations), et de préparer ces données en vue de leur utilisation pour
    l'entraînement et l'inférence de modèles.

    Pour commencer, rendez-vous dans l'onglet **Mode d'emploi** (menu à gauche) afin de
    connaître les prérequis, puis dans l'onglet **Connexion** pour accéder à votre espace
    personnel.
    """
)