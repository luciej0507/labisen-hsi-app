"""Interface de l'étape 4 (Lancement et suivi) de la page Apprentissage.

Logique métier dans modules/apprentissage/etape_lancement_suivi.py et
modules/apprentissage/gestion_entrainement.py.

Disposition du suivi d'un entraînement :
  - une ligne d'en-tête : badge d'état et bouton "Configuration" (popover) ;
  - un bandeau de chiffres clés (époque, loss, GPU) et la barre de progression ;
  - deux colonnes : à gauche les onglets "Courbe de loss" et "Journal",
    à droite la tuile MLflow et les boutons d'action ;
  - sous un entraînement fini : le panneau "Relancer un entraînement".
"""

import base64
from html import escape
from pathlib import Path

import pandas as pd
import streamlit as st

from modules.apprentissage.etape_lancement_suivi import (
    ETATS_ACTIFS,
    blocs_recapitulatif,
    etat_du_run,
    lire_etat_gpus,
    url_mlflow,
)
from modules.apprentissage.gestion_entrainement import (
    arreter_entrainement,
    lancer_entrainement,
    lire_log,
    lire_log_filtre,
    lire_run_en_cours,
    oublier_run,
)
from ui.apprentissage import etat
from ui.apprentissage.alerte_service import (
    afficher_alerte_service_arrete,
    service_calcul_actif,
)
from ui.apprentissage.styles import (
    TEINTES,
    css_cartes_gpu,
    css_cartes_recapitulatif,
    css_tuile_mlflow,
)

# Délai (en secondes) entre deux rafraîchissements du suivi
INTERVALLE_SUIVI = 2

# Logo affiché dans la tuile MLflow
LOGO_MLFLOW = Path(__file__).parent / "assets" / "mlflow_logo.png"

# Délai (en secondes) entre deux rafraîchissements de l'état des GPU.
# Le worker ne publie qu'un relevé toutes les 5 secondes : aller plus vite
# n'apporterait rien.
INTERVALLE_GPUS = 5

# Clé de st.session_state qui contient l'indice du GPU choisi
CLE_GPU = "appr_gpu"

# Nombre maximum de cartes GPU sur une même ligne
GPU_PAR_LIGNE = 4

# Seuils de charge (en %) : en dessous de 50 le GPU est libre, en dessous
# de 80 il est modéré, au delà il est chargé
SEUIL_CHARGE = 80

# Température (en °C) au delà de laquelle on déconseille d'utiliser le GPU
SEUIL_TEMPERATURE = 85

# Pour chaque état : (limite en %, libellé, couleur du texte, couleur de remplissage)
ETATS_GPU = [
    (50, "Libre", "#1a7a45", "#1f9d55"),
    (SEUIL_CHARGE, "Modéré", "#a8510a", "#d9730d"),
    (101, "Chargé", "#b30d27", "#c8102e"),
]

# Texte et couleur du badge pour chaque état de l'entraînement
LIBELLES_ETAT = {
    "demarrage": ("Démarrage", "orange"),
    "en_cours": ("En cours", "blue"),
    "termine": ("Terminé", "green"),
    "arrete": ("Arrêté", "gray"),
    "erreur": ("Erreur", "red"),
}


# ---------------------------------------------------------------------------
# Récapitulatif de la configuration
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Choix du GPU
# ---------------------------------------------------------------------------

def etat_gpu(pourcentage):
    """Renvoie (libellé, couleur du texte, couleur de remplissage) selon une charge en %."""
    for limite, libelle, couleur_texte, couleur in ETATS_GPU:
        if pourcentage < limite:
            return libelle, couleur_texte, couleur
    # Ne devrait jamais arriver (la dernière limite dépasse 100 %)
    return ETATS_GPU[-1][1:]


def gpu_recommande(gpus):
    """Renvoie l'indice du GPU le moins utilisé (None s'il n'y a qu'un seul GPU)."""
    if len(gpus) < 2:
        return None
    moins_charge = min(gpus, key=lambda g: (g["utilisation"], g["memoire_utilisee"]))
    return moins_charge["index"]

def html_carte_gpu(gpu, recommande, suivi=False):
    """
    Construit le HTML d'une carte GPU : nom, état, donut d'utilisation, barre de mémoire.

    Si suivi vaut True (carte affichée pendant un entraînement), le libellé
    "Libre / Modéré / Chargé" est masqué et la carte indique "Cet entraînement".
    """
    utilisation = gpu["utilisation"]
    libelle, couleur_texte, couleur = etat_gpu(utilisation)

    # Part de mémoire utilisée, en % (sans division par zéro)
    totale = gpu["memoire_totale"]
    part_memoire = round(100 * gpu["memoire_utilisee"] / totale) if totale else 0
    couleur_memoire = etat_gpu(part_memoire)[2]

    if suivi:
        # Pendant un entraînement, le GPU est normalement "Chargé" : on ne l'écrit pas
        texte_reco = "Cet entraînement"
        badge_etat = ""
    else:
        # Espace insécable quand le GPU n'est pas recommandé : toutes les cartes
        # gardent ainsi la même hauteur
        texte_reco = "Recommandé" if recommande else "&nbsp;"
        badge_etat = (
            f'<span class="gpu-etat" style="--t:{couleur_texte}; --c:{couleur}">{libelle}</span>'
        )

    # Température en texte simple ("-" si le GPU ne la communique pas)
    temperature = gpu.get("temperature")
    texte_temperature = f"{temperature} °C" if temperature is not None else "-"

    # Tout le HTML est sur une seule ligne : un retour à la ligne suivi
    # d'espaces serait pris pour du code par le Markdown
    return (
        '<div class="gpu-entete">'
        f'<span class="gpu-nom">GPU {gpu["index"]}</span>'
        f"{badge_etat}"
        "</div>"
        f'<div class="gpu-reco">{texte_reco}</div>'
        f'<div class="gpu-donut" style="--p:{utilisation}; --c:{couleur}">'
        f"<span>{utilisation} %</span></div>"
        '<div class="gpu-legende">Utilisation</div>'
        '<div class="gpu-memoire"><span>Mémoire</span>'
        f'<span>{gpu["memoire_utilisee"]} / {totale} Go</span></div>'
        '<div class="gpu-barre">'
        f'<div style="width:{min(part_memoire, 100)}%; background:{couleur_memoire}"></div>'
        "</div>"
        '<div class="gpu-memoire"><span>Température</span>'
        f"<span>{texte_temperature}</span></div>"
    )


def choisir_gpu(index):
    """Mémorise le GPU choisi (appelée au clic sur le bouton d'une carte)."""
    st.session_state[CLE_GPU] = index


def carte_gpu(gpu, choisi, recommande):
    """Affiche une carte GPU avec son bouton de sélection."""
    index = gpu["index"]
    # La clé du conteneur donne la classe CSS de la carte (bordure rouge si choisie)
    cle = f"gpu-choisie-{index}" if choisi else f"gpu-carte-{index}"
    with st.container(key=cle):
        st.markdown(html_carte_gpu(gpu, recommande), unsafe_allow_html=True)
        st.button(
            "Sélectionné" if choisi else "Choisir",
            key=f"gpu_bouton_{index}",
            on_click=choisir_gpu,
            args=(index,),
            type="primary" if choisi else "secondary",
            width="stretch",
        )
        
def carte_gpu_entrainement(index_gpu):
    """Affiche l'état en temps réel du GPU utilisé par l'entraînement (sans bouton de choix)."""
    # Le numéro du GPU n'est connu que lorsque le run a démarré
    if index_gpu is None:
        return

    # Relevé publié par le worker, puis recherche du GPU de l'entraînement
    releve = lire_etat_gpus()
    gpu = next((g for g in releve["gpus"] if g["index"] == index_gpu), None)
    if not releve["worker_actif"] or gpu is None:
        st.caption("État du GPU indisponible pour le moment.")
        return

    # La clé du conteneur donne la classe CSS de la carte (bordure rouge)
    with st.container(key=f"gpu-carte-{index_gpu}"):
        st.markdown(html_carte_gpu(gpu, False, suivi=True), unsafe_allow_html=True)


@st.fragment(run_every=INTERVALLE_GPUS)
def section_serveur():
    """
    Bloc de l'étape 4 : état des GPU en temps réel et choix d'un GPU.

    C'est un fragment : il se rafraîchit tout seul toutes les INTERVALLE_GPUS
    secondes, sans recharger la page. Le GPU choisi est stocké dans
    st.session_state[CLE_GPU] (None si aucun GPU n'est disponible).
    """
    # L'état des GPU est relevé par le worker et publié dans MongoDB
    releve = lire_etat_gpus()
    gpus = releve["gpus"]

    if not releve["worker_actif"]:
        st.session_state[CLE_GPU] = None
        afficher_alerte_service_arrete("lancement_entrainement")
        return

    if not gpus:
        st.session_state[CLE_GPU] = None
        st.error(
            "Aucun GPU n'a été détecté sur la machine qui exécute les "
            "calculs. Prévenez l'administrateur de la plateforme."
        )
        return

    st.markdown("**Choix du GPU**")

    # Si aucun GPU valide n'est choisi, on prend le GPU recommandé (ou le premier)
    recommande = gpu_recommande(gpus)
    indices = [g["index"] for g in gpus]
    if st.session_state.get(CLE_GPU) not in indices:
        st.session_state[CLE_GPU] = recommande if recommande is not None else indices[0]
    choisi = st.session_state[CLE_GPU]

    # Une carte par GPU, GPU_PAR_LIGNE cartes au maximum par ligne
    for debut in range(0, len(gpus), GPU_PAR_LIGNE):
        lot = gpus[debut:debut + GPU_PAR_LIGNE]
        for colonne, gpu in zip(st.columns(GPU_PAR_LIGNE), lot):
            with colonne:
                carte_gpu(gpu, gpu["index"] == choisi, gpu["index"] == recommande)

    # Avertissement si le GPU choisi est déjà très utilisé
    utilisation = next(g["utilisation"] for g in gpus if g["index"] == choisi)
    if utilisation >= SEUIL_CHARGE:
        st.warning(
            f"Le GPU {choisi} est déjà utilisé à {utilisation} % : "
            "l'entraînement risque d'être lent ou de manquer de mémoire."
        )
        
    # Avertissement si le GPU choisi est trop chaud
    temperature = next(g.get("temperature") for g in gpus if g["index"] == choisi)
    if temperature is not None and temperature > SEUIL_TEMPERATURE:
        st.warning(
            f"Le GPU {choisi} est à {temperature} °C : au delà de "
            f"{SEUIL_TEMPERATURE} °C, son utilisation est déconseillée. "
            "Choisissez un autre GPU ou attendez qu'il refroidisse."
        )

    st.caption(
        f"Relevé effectué il y a {releve['age_secondes']} s. "
        f"Mise à jour automatique toutes les {INTERVALLE_GPUS} s."
    )


# ---------------------------------------------------------------------------
# Lancement et arrêt
# ---------------------------------------------------------------------------

def section_lancement(config, gpu):
    """Bouton de lancement : démarre l'entraînement puis affiche le suivi."""
    if st.button("Lancer l'entraînement", type="primary", disabled=gpu is None):
        if gpu is None:
            st.error("Aucun GPU n'est disponible pour lancer l'entraînement.")
            return
        try:
            with st.spinner("Démarrage de l'entraînement..."):
                lancer_entrainement(
                    st.session_state[etat.DATASET], config, gpu,
                    utilisateur=st.session_state.get("username"),
                )
        except Exception as erreur:
            st.error(f"Impossible de lancer l'entraînement : {erreur}")
        else:
            st.rerun()


def section_relance():
    """Permet de relancer un entraînement sous un run terminé, arrêté ou en erreur."""
    # Configuration validée à l'étape 3 (None si elle n'a pas été validée)
    config = st.session_state.get(etat.CONFIG)

    st.divider()
    st.markdown("**Relancer un entraînement**")

    if config is None:
        st.info("Validez d'abord une configuration à l'étape Paramétrage.")
        return

    st.caption(
        "L'entraînement sera lancé avec la configuration validée à l'étape 3."
    )
    # Choix du GPU (le fragment le range dans la session), puis bouton de lancement
    section_serveur()
    section_lancement(config, st.session_state.get(CLE_GPU))


def boutons_arret():
    """Bouton d'arrêt, avec une confirmation avant d'arrêter l'entraînement."""
    if st.session_state.get(etat.CONFIRMER_ARRET):
        st.warning(
            "Arrêter l'entraînement ? Le processus sera stoppé et le GPU libéré. "
            "Les époques déjà faites ne seront pas reprises."
        )
        oui, non = st.columns(2)
        if oui.button("Oui, arrêter", type="primary", width="stretch"):
            with st.spinner("Arrêt en cours..."):
                arreter_entrainement()
            st.session_state[etat.CONFIRMER_ARRET] = False
            st.rerun()
        if non.button("Annuler", width="stretch"):
            st.session_state[etat.CONFIRMER_ARRET] = False
            st.rerun(scope="fragment")
    elif st.button("Arrêter l'entraînement", width="stretch"):
        st.session_state[etat.CONFIRMER_ARRET] = True
        st.rerun(scope="fragment")


# ---------------------------------------------------------------------------
# Éléments du tableau de bord
# ---------------------------------------------------------------------------

def logo_mlflow_base64():
    """Lit le logo MLflow et le renvoie encodé en texte, pour l'intégrer dans le HTML.

    Renvoie un texte vide si le fichier du logo est introuvable. Le résultat
    n'est volontairement pas mis en cache : le fichier est léger, et un logo
    ajouté après coup apparaît tout de suite.
    """
    try:
        return base64.b64encode(LOGO_MLFLOW.read_bytes()).decode()
    except OSError:
        return ""


def tuile_mlflow(url):
    """Affiche une tuile cliquable (logo MLflow) qui ouvre le suivi dans un nouvel onglet."""
    logo = logo_mlflow_base64()
    if logo:
        image = f'<img src="data:image/png;base64,{logo}" alt="Logo MLflow">'
    else:
        # Logo introuvable : on affiche le nom en texte (vérifiez LOGO_MLFLOW)
        image = '<span class="tuile-titre">MLflow</span>'

    # Tout le HTML est sur une seule ligne : un retour à la ligne suivi
    # d'espaces serait pris pour du code par le Markdown.
    # Le lien ne contient que des <span> : avec des <div> à l'intérieur,
    # Streamlit découpe le lien en plusieurs morceaux (une tuile par bloc).
    html = (
        f'<a class="tuile-mlflow" href="{escape(url)}" target="_blank" rel="noopener noreferrer">'
        f"{image}"
        '<span class="tuile-texte">Suivi des entraînements et registre de modèles</span>'
        '<span class="tuile-bas">'
        '<span class="tuile-ouvrir">Ouvrir →</span>'
        "</span></a>"
    )
    st.markdown(html, unsafe_allow_html=True)


def entete(run, etat_run):
    """Ligne d'en-tête : badge d'état à gauche, bouton "Configuration" à droite."""
    libelle, couleur = LIBELLES_ETAT[etat_run]
    # Tant que le worker n'a pas démarré le job, l'état affiché est "En attente"
    if run["en_attente"]:
        libelle, couleur = "En attente", "orange"

    gauche, droite = st.columns([4, 1], vertical_alignment="center")
    with gauche:
        st.badge(libelle, color=couleur)
        st.caption("L'entraînement continue de tourner même si vous quittez l'application.")
    with droite:
        # Le récapitulatif de la configuration s'ouvre au clic, sans prendre de place
        if run["config"]:
            with st.popover("Configuration"):
                section_recapitulatif(run["config"])


def messages_etat(run, etat_run, actif):
    """Affiche les messages utiles : attente, démarrage, arrêt, erreur, service arrêté."""
    if run["en_attente"]:
        st.info(
            "En attente de démarrage : la demande est enregistrée, "
            "l'entraînement démarrera dès que le service de calcul sera libre."
        )
    elif etat_run == "demarrage":
        st.info("Démarrage : chargement des bibliothèques, des données et du modèle...")
    elif etat_run == "arrete":
        st.warning("Entraînement arrêté à votre demande. Le GPU est libéré.")
    elif etat_run == "erreur":
        message = run["statut"].get("message") or (
            "Le processus s'est arrêté de façon inattendue. Consultez le journal."
        )
        st.error(f"Entraînement en erreur : {message}")

    # Si le service de calcul est arrêté, rien ne va avancer : on prévient
    if actif and not service_calcul_actif():
        afficher_alerte_service_arrete("attente" if run["en_attente"] else "en_cours")
    if actif and run["arret_demande"]:
        st.info(
            "Arrêt demandé : le service de calcul arrête l'entraînement, "
            "cela peut prendre quelques secondes."
        )


def bandeau_chiffres(statut):
    """Deux chiffres clés sur une ligne : époque et loss."""
    total = statut.get("total_epochs")
    epoque = statut.get("epoch", 0)
    loss = statut.get("loss")

    colonne_epoque, colonne_loss = st.columns(2)
    colonne_epoque.metric(
        "Époque", f"{epoque} / {total}" if total else "-", border=True
    )
    colonne_loss.metric(
        "Loss (dernière époque)", f"{loss:.4f}" if loss is not None else "-", border=True
    )


def barre_progression(statut):
    """Barre de progression de l'entraînement (rien tant que le total d'époques est inconnu)."""
    total = statut.get("total_epochs")
    if not total:
        return
    epoque = statut.get("epoch", 0)
    part = min(epoque / total, 1.0)
    st.progress(part, text=f"{round(part * 100)} % de l'entraînement")


# ---------------------------------------------------------------------------
# Suivi
# ---------------------------------------------------------------------------

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

    # --- Haut de page : état, messages, chiffres clés, progression ---
    entete(run, etat_run)
    messages_etat(run, etat_run, actif)
    bandeau_chiffres(statut)
    barre_progression(statut)

    # --- Corps : à gauche courbe et journal, à droite MLflow et actions ---
    gauche, droite = st.columns([2, 1])

    with gauche:
        onglet_journal, onglet_courbe = st.tabs(["Journal", "Courbe de loss"])
        with onglet_courbe:
            historique = statut.get("historique_loss", [])
            if len(historique) >= 2:
                # Un tableau avec le numéro de chaque époque (à partir de 1) et sa loss
                courbe = pd.DataFrame({
                    "Époque": range(1, len(historique) + 1),
                    "Loss": historique,
                })
                st.line_chart(
                    courbe,
                    x="Époque",
                    y="Loss",
                    x_label="Époque",
                    y_label="Loss",
                )
            else:
                st.caption("La courbe apparaît à partir de la deuxième époque.")
        with onglet_journal:
            # Vue épurée : uniquement les lignes écrites par le script d'entraînement
            journal = lire_log_filtre(run["dossier"], arret_demande=run["arret_demande"])
            st.code(journal or "Aucune sortie pour le moment.", language=None)

            # Journal brut (avertissements, traceback) pour le dépannage
            with st.expander("Journal complet"):
                brut = lire_log(run["dossier"], nb_lignes=60)
                st.code(brut or "Aucune sortie pour le moment.", language=None)
    with droite:
        # État en temps réel du GPU de l'entraînement (tant qu'il est actif)
        if actif:
            carte_gpu_entrainement(run["config"].get("gpu"))
        tuile_mlflow(url_mlflow(statut))
        if actif:
            # Une fois l'arrêt demandé, le bouton d'arrêt n'a plus lieu d'être
            if not run["arret_demande"]:
                boutons_arret()
        elif st.button("Nouvel entraînement", width="stretch"):
            oublier_run()
            st.rerun()


def section_suivi(run):
    """Affiche le suivi d'un entraînement lancé (en cours ou terminé)."""
    # Rafraîchissement automatique seulement tant que l'entraînement est actif
    etait_actif = etat_du_run(run) in ETATS_ACTIFS
    fragment = st.fragment(run_every=INTERVALLE_SUIVI if etait_actif else None)(
        suivi_entrainement
    )
    fragment(etait_actif)

    # Si l'entraînement est fini (terminé, arrêté ou en erreur), on propose de relancer
    if not etait_actif:
        section_relance()


def etape_lancement():
    """Étape 4 : rappel de la configuration, choix du GPU, lancement et suivi."""
    st.subheader("Lancement et suivi")
    # Style de la tuile MLflow et des cartes GPU
    st.markdown(css_tuile_mlflow(), unsafe_allow_html=True)
    st.markdown(css_cartes_gpu(), unsafe_allow_html=True)

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
    section_serveur()
    section_lancement(config, st.session_state.get(CLE_GPU))