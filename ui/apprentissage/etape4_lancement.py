"""Interface de l'étape 4 (Lancement et suivi) de la page Apprentissage.

Logique métier dans modules/apprentissage/etape_lancement_suivi.py.
"""

import pandas as pd
import streamlit as st

from modules.apprentissage.etape_lancement_suivi import (
    TITRE_BLOC_GPU,
    blocs_recapitulatif,
    libelle_gpu,
    lignes_gpus,
    lire_gpus,
)
from ui.apprentissage import etat
from ui.apprentissage.styles import (
    TEINTES,
    css_blocs_parametrage,
    css_cartes_recapitulatif,
)


def bloc_recapitulatif(titre, teinte, lignes):
    """Affiche une section du récapitulatif : titre coloré, puis une ligne "nom : valeur" par choix."""
    couleur = TEINTES[teinte][1]
    # La clé du conteneur donne la classe CSS qui dessine la barre colorée
    with st.container(key=f"recap-{teinte}"):
        st.markdown(
            f'<span style="color:{couleur}; font-weight:600">{titre}</span>',
            unsafe_allow_html=True,
        )
        # Une seule ligne par choix : le nom en gris, la valeur en gras.
        # Deux espaces + retour = saut de ligne.
        st.markdown(
            "  \n".join(f":gray[{nom}] : **{valeur}**" for nom, valeur in lignes)
        )


def section_recapitulatif(config):
    """Rappelle la configuration validée à l'étape 3, dans un seul cadre à deux colonnes."""
    st.markdown("**Récapitulatif de la configuration**")
    st.markdown(css_cartes_recapitulatif(), unsafe_allow_html=True)

    blocs = blocs_recapitulatif(config)
    # Colonne de gauche : blocs 1 et 2. Colonne de droite : blocs 3 et 4.
    # Les deux colonnes ont ainsi à peu près la même hauteur.
    with st.container(border=True):
        gauche, droite = st.columns(2)
        for colonne, lot in ((gauche, blocs[:2]), (droite, blocs[2:])):
            with colonne:
                for titre, teinte, lignes in lot:
                    bloc_recapitulatif(titre, teinte, lignes)


def section_serveur():
    """Bloc de l'étape 4 : état des GPU et choix d'un GPU. Retourne l'indice choisi."""
    with st.container(key="bloc-vert"), st.expander(TITRE_BLOC_GPU, expanded=True):
        # Pour l'instant les données sont factices (voir lire_gpus)
        st.caption(
            "Données de démonstration : la lecture réelle de l'état des GPU "
            "sera branchée ultérieurement."
        )
        gpus = lire_gpus()
        st.dataframe(
            pd.DataFrame(lignes_gpus(gpus)),
            hide_index=True,
            width="stretch",
            column_config={
                "Utilisation (%)": st.column_config.ProgressColumn(
                    "Utilisation (%)", min_value=0, max_value=100, format="%d"
                )
            },
        )
        # Un clic relance la page, ce qui relit l'état des GPU
        st.button("Actualiser l'état des GPU")

        libelles = {g["index"]: libelle_gpu(g) for g in gpus}
        gpu = st.radio(
            "Choix du GPU",
            list(libelles),
            format_func=libelles.get,
            horizontal=True,
            key="appr_gpu",
        )
    return gpu


def etape_lancement():
    """Étape 4 : rappel de la configuration, choix du GPU et lancement."""
    st.subheader("Lancement et suivi")
    # Couleurs des expanders (celle du bloc GPU)
    st.markdown(css_blocs_parametrage(), unsafe_allow_html=True)

    # Cette étape n'est accessible qu'une fois la configuration validée
    config = st.session_state[etat.CONFIG]
    if config is None:
        st.warning("Aucune configuration validée : retournez à l'étape Paramétrage.")
        return

    st.caption(
        "Vérifiez la configuration, choisissez le GPU, puis lancez l'entraînement."
    )
    section_recapitulatif(config)
    st.divider()
    gpu = section_serveur()

    # Ébauche : le lancement n'est pas encore branché
    if st.button("Lancer l'entraînement", type="primary"):
        st.info(
            f"Lancement pas encore branché : l'entraînement serait lancé sur le GPU {gpu}. "
            "Le suivi dans MLflow sera ajouté ensuite."
        )
