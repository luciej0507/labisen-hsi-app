"""Navigation de la page Apprentissage : frise des étapes et bouton retour."""

import streamlit as st

from modules.apprentissage.frise import ETAPES, etape_accessible, libelle_etape
from ui.apprentissage import etat
from ui.apprentissage.styles import css_etapes_validees


def frise(validees):
    """Affiche la frise : un bouton par étape, sur une seule ligne.

    L'étape active est en couleur, une étape validée est en vert. Une étape
    est désactivée tant que les étapes précédentes ne sont pas validées.
    """
    # Injection du CSS des étapes validées (rien à injecter sinon)
    css = css_etapes_validees(validees)
    if css:
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)

    colonnes = st.columns(len(ETAPES))
    for index, colonne in enumerate(colonnes):
        actif = st.session_state[etat.ETAPE] == index
        clic = colonne.button(
            libelle_etape(index, validees[index]),
            key=f"frise_{index}",
            type="primary" if actif else "secondary",
            disabled=not etape_accessible(index, validees),
            width="stretch",
        )
        # Clic sur une étape : on la rend active et on recharge la page
        if clic:
            st.session_state[etat.ETAPE] = index
            st.rerun()


def bouton_retour():
    """Affiche un bouton pour revenir à l'étape précédente (dès la 2e étape).

    Revenir en arrière ne réinitialise rien : seule l'étape active change,
    comme lors d'un clic sur la frise.
    """
    etape = st.session_state[etat.ETAPE]
    # Pas de retour possible depuis la première étape
    if etape == 0:
        return

    st.divider()
    if st.button("Retour à l'étape précédente", key="bouton_retour"):
        st.session_state[etat.ETAPE] = etape - 1
        st.rerun()
