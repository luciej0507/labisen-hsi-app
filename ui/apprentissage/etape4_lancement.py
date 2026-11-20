"""Interface de l'étape 4 (Lancement et suivi) de la page Apprentissage.

Logique métier dans modules/apprentissage/etape_lancement_suivi.py et
modules/apprentissage/gestion_entrainement.py.
"""

import pandas as pd
import streamlit as st

from modules.apprentissage.etape_lancement_suivi import (
    ETATS_ACTIFS,
    TITRE_BLOC_GPU,
    blocs_recapitulatif,
    etat_du_run,
    libelle_gpu,
    lignes_gpus,
    lire_gpus,
    url_mlflow,
)
from modules.apprentissage.gestion_entrainement import (
    arreter_entrainement,
    lancer_entrainement,
    lire_log,
    lire_run_en_cours,
    oublier_run,
)
from ui.apprentissage import etat
from ui.apprentissage.styles import (
    TEINTES,
    css_blocs_parametrage,
    css_cartes_recapitulatif,
)

# Délai (en secondes) entre deux rafraîchissements du suivi
INTERVALLE_SUIVI = 2


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
    """Bloc de l'étape 4 : état des GPU et choix d'un GPU. Retourne l'indice choisi (None si aucun GPU)."""
    with st.container(key="bloc-vert"), st.expander(TITRE_BLOC_GPU, expanded=True):
        gpus = lire_gpus()
        if not gpus:
            st.error("Aucun GPU détecté : la commande nvidia-smi n'a rien renvoyé.")
            return None

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


def section_lancement(config, gpu):
    """Bouton de lancement : démarre l'entraînement puis affiche le suivi."""
    if st.button("Lancer l'entraînement", type="primary", disabled=gpu is None):
        try:
            with st.spinner("Démarrage de l'entraînement..."):
                lancer_entrainement(st.session_state[etat.DATASET], config, gpu)
        except Exception as erreur:
            st.error(f"Impossible de lancer l'entraînement : {erreur}")
        else:
            st.rerun()


def boutons_arret():
    """Bouton d'arrêt, avec une confirmation avant d'arrêter l'entraînement."""
    if st.session_state.get(etat.CONFIRMER_ARRET):
        st.warning(
            "Arrêter l'entraînement ? Le processus sera stoppé et le GPU libéré. "
            "Les époques déjà faites ne seront pas reprises."
        )
        oui, non, _ = st.columns([1, 1, 3])
        if oui.button("Oui, arrêter", type="primary"):
            with st.spinner("Arrêt en cours..."):
                arreter_entrainement()
            st.session_state[etat.CONFIRMER_ARRET] = False
            st.rerun()
        if non.button("Annuler"):
            st.session_state[etat.CONFIRMER_ARRET] = False
            st.rerun(scope="fragment")
    elif st.button("Arrêter l'entraînement"):
        st.session_state[etat.CONFIRMER_ARRET] = True
        st.rerun(scope="fragment")


def suivi_entrainement(etait_actif):
    """
    Affiche l'état de l'entraînement. Cette fonction est un fragment : tant que
    l'entraînement est actif, elle se relance toute seule sans recharger la page.
    """
    run = lire_run_en_cours()
    if run is None:
        st.rerun()

    etat_run = etat_du_run(run)
    actif = etat_run in ETATS_ACTIFS

    # L'entraînement vient de se terminer : on recharge toute la page,
    # ce qui arrête le rafraîchissement automatique
    if etait_actif and not actif:
        st.rerun()

    statut = run["statut"]

    # --- Message d'état ---
    if etat_run == "demarrage":
        st.info("Démarrage : chargement des bibliothèques, des données et du modèle...")
    elif etat_run == "en_cours":
        st.info("Entraînement en cours.")
    elif etat_run == "termine":
        st.success("Entraînement terminé.")
    elif etat_run == "arrete":
        st.warning("Entraînement arrêté. Le GPU est libéré.")
    else:
        message = statut.get("message") or (
            "Le processus s'est arrêté de façon inattendue. Consultez le journal."
        )
        st.error(f"Entraînement en erreur : {message}")

    # --- Progression ---
    total = statut.get("total_epochs")
    if total:
        epoque = statut.get("epoch", 0)
        st.progress(min(epoque / total, 1.0), text=f"Époque {epoque} sur {total}")

    loss = statut.get("loss")
    if loss is not None:
        st.metric("Loss d'entraînement (dernière époque)", f"{loss:.4f}")

    historique = statut.get("historique_loss", [])
    if len(historique) >= 2:
        st.line_chart(pd.DataFrame({"loss": historique}))

    # --- Lien MLflow et boutons ---
    st.link_button("Ouvrir le suivi dans MLflow", url_mlflow(statut))
    if actif:
        boutons_arret()
    elif st.button("Nouvel entraînement", type="primary"):
        oublier_run()
        st.rerun()

    # --- Journal ---
    with st.expander("Journal d'entraînement"):
        st.code(lire_log(run["dossier"]) or "Aucune sortie pour le moment.", language=None)


def section_suivi(run):
    """Affiche le suivi d'un entraînement lancé (en cours ou terminé)."""
    st.caption("L'entraînement continue de tourner même si vous quittez l'application.")

    # Configuration du run lui-même (relue dans son config.json)
    if run["config"]:
        with st.expander("Configuration de cet entraînement"):
            section_recapitulatif(run["config"])

    # Rafraîchissement automatique seulement tant que l'entraînement est actif
    etait_actif = etat_du_run(run) in ETATS_ACTIFS
    fragment = st.fragment(run_every=INTERVALLE_SUIVI if etait_actif else None)(
        suivi_entrainement
    )
    fragment(etait_actif)


def etape_lancement():
    """Étape 4 : rappel de la configuration, choix du GPU, lancement et suivi."""
    st.subheader("Lancement et suivi")
    # Couleurs des expanders (celle du bloc GPU)
    st.markdown(css_blocs_parametrage(), unsafe_allow_html=True)

    # Un entraînement existe déjà (en cours ou terminé) : on affiche son suivi
    run = lire_run_en_cours()
    if run is not None:
        section_suivi(run)
        return

    # Sinon, cette étape n'est accessible qu'une fois la configuration validée
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
    section_lancement(config, gpu)