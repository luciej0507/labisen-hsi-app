"""Clés de l'état de session (st.session_state) de la page Apprentissage.

Toutes les clés sont regroupées ici pour éviter les fautes de frappe : les
autres fichiers importent ces constantes au lieu d'écrire les textes à la main.
Les clés propres à un seul champ (par exemple "appr_modele") restent dans le
fichier du champ.
"""

import streamlit as st

# Parcours : étape active, dataset validé, format de patches et configuration
ETAPE = "appr_etape"
DATASET = "appr_dataset"
VERSION = "appr_version"
CONFIG = "appr_config"

# Indice de l'étape Lancement et suivi dans la frise
ETAPE_LANCEMENT = 3

# Étape 1 : carte sélectionnée, et changement de dataset en attente de confirmation
SELECTION = "appr_selection"
CONFIRMER_CHANGEMENT = "appr_confirmer_changement"

# Étape 2 : annulation du patching en attente de confirmation
CONFIRMER_ANNULATION = "appr_confirmer_annulation"

# Étape 4 : arrêt de l'entraînement en attente de confirmation
CONFIRMER_ARRET = "appr_confirmer_arret"

# Message affiché une seule fois après une action
MESSAGE = "appr_message"


def initialiser():
    """Crée les clés du parcours avec leur valeur de départ si elles n'existent pas."""
    st.session_state.setdefault(ETAPE, 0)
    st.session_state.setdefault(DATASET, None)
    st.session_state.setdefault(VERSION, None)
    st.session_state.setdefault(CONFIG, None)