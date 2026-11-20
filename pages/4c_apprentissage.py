"""
Page Apprentissage : section de l'espace de travail (rôle user).

Parcours en 4 étapes affiché sous forme de frise : Dataset, Patching,
Paramétrage, Lancement et suivi. Ce fichier ne fait qu'assembler la page :
l'interface de chaque étape est dans ui/apprentissage/ et la logique métier
dans modules/apprentissage/.
"""

import streamlit as st

from modules.apprentissage.frise import etapes_validees
from modules.apprentissage.gestion_entrainement import lire_run_en_cours
from modules.comptes.auth import require_role
from ui.apprentissage import etat
from ui.apprentissage.etape1_dataset import etape_dataset
from ui.apprentissage.etape4_lancement import etape_lancement
from ui.apprentissage.navigation import bouton_retour, frise
from ui.apprentissage.etape3_parametrage import etape_parametrage
from ui.apprentissage.etape2_patching import etape_patching
from ui.sidebar import render_sidebar
from ui.topnav import configurer_page, render_topnav

# Fonction d'affichage de chaque étape, dans l'ordre de la frise
FONCTIONS_ETAPES = [etape_dataset, etape_patching, etape_parametrage, etape_lancement]


def main():
    """Assemble l'en-tête commun, la frise et l'étape active."""
    # Configuration de la page (doit être la première commande Streamlit).
    configurer_page("Apprentissage")

    # En-tête, contrôle d'accès (rôle user) et menu latéral.
    render_topnav("Mon Espace")
    require_role("user")
    render_sidebar("Apprentissage")

    st.title("Apprentissage")
    st.write("Suivez les étapes pour entraîner un modèle sur vos cubes HSI.")

    # État du parcours : étape active, dataset, version de patches et configuration
    etat.initialiser()

    validees = etapes_validees(
        st.session_state[etat.DATASET],
        st.session_state[etat.VERSION],
        st.session_state[etat.CONFIG],
    )
    frise(validees)
    st.divider()

    # Message laissé par l'action précédente (affiché une seule fois)
    message = st.session_state.pop(etat.MESSAGE, None)
    if message:
        st.success(message)

    # Entraînement lancé précédemment : retrouvé même après avoir quitté l'application
    if (
        lire_run_en_cours() is not None
        and st.session_state[etat.ETAPE] != etat.ETAPE_LANCEMENT
    ):
        st.info("Un entraînement lancé précédemment est disponible.")
        if st.button("Voir le suivi de l'entraînement"):
            st.session_state[etat.ETAPE] = etat.ETAPE_LANCEMENT
            st.rerun()

    # Affichage de l'étape active
    FONCTIONS_ETAPES[st.session_state[etat.ETAPE]]()

    # Bouton retour en bas de page, sous l'étape active
    bouton_retour()


main()