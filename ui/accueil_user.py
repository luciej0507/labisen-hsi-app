"""
ui/accueil_user.py

Interface de la page Accueil de l'espace utilisateur :
  - la carte de l'entraînement en cours (s'il y en a un) ;
  - l'historique des entraînements terminés de l'utilisateur.

Les données sont préparées dans modules/accueil_user.py.
"""

import streamlit as st
from streamlit.errors import StreamlitAPIException

from modules.accueil_user import lire_entrainement_en_cours, lister_historique
from ui.apprentissage.etape4_lancement import LIBELLES_ETAT

# Délai (en secondes) entre deux rafraîchissements de la carte "en cours"
INTERVALLE_SUIVI = 5

# Page Apprentissage (à adapter si le fichier porte un autre nom)
PAGE_APPRENTISSAGE = "pages/4c_apprentissage.py"

# Nombre d'entraînements affichés dans l'historique, et pas du bouton "Voir plus"
NB_PAR_PAGE = 10

# Clé de st.session_state qui contient le nombre de lignes affichées
CLE_NB_LIGNES = "accueil_nb_entrainements"

# Texte et couleur du badge pour chaque état (ceux de l'étape 4, plus "En attente")
LIBELLES = {**LIBELLES_ETAT, "en_attente": ("En attente", "orange")}

# Colonnes de l'historique : titres et largeurs relatives
TITRES_COLONNES = [
    "Date et heure", "Dataset", "Modèle", "État",
    "Époques", "Dernière loss", "Durée", "MLflow",
]
LARGEURS_COLONNES = [2, 2, 1.5, 1.5, 1.2, 1.6, 1.4, 1]


# ---------------------------------------------------------------------------
# Petits textes
# ---------------------------------------------------------------------------

def texte_epoques(resume):
    """Renvoie "2 / 5", ou "-" si l'époque ou le total est inconnu."""
    if resume["epoque"] is None or resume["total_epochs"] is None:
        return "-"
    return f"{resume['epoque']} / {resume['total_epochs']}"


def texte_loss(resume):
    """Renvoie la loss avec 4 décimales, ou "-" si elle est inconnue."""
    if resume["loss"] is None:
        return "-"
    return f"{resume['loss']:.4f}"


# ---------------------------------------------------------------------------
# Entraînement en cours
# ---------------------------------------------------------------------------

@st.fragment(run_every=INTERVALLE_SUIVI)
def section_en_cours(utilisateur):
    """
    Carte de l'entraînement en cours de l'utilisateur.

    C'est un fragment : il se rafraîchit tout seul toutes les INTERVALLE_SUIVI
    secondes, sans recharger la page.
    """
    run = lire_entrainement_en_cours(utilisateur)
    if run is None:
        st.info("Aucun entraînement en cours.")
        return

    libelle, couleur = LIBELLES[run["etat"]]
    gpu = run["gpu"]

    with st.container(border=True):
        st.badge(libelle, color=couleur)
        st.markdown(
            f":gray[Dataset] : **{run['dataset']}**  \n"
            f":gray[Modèle] : **{run['modele']}**"
        )

        # Barre de progression (le total d'époques n'est connu qu'au démarrage)
        total = run["total_epochs"]
        if total:
            epoque = run["epoque"] or 0
            st.progress(min(epoque / total, 1.0), text=f"Époque {epoque} / {total}")
        else:
            st.caption("Le calcul n'a pas encore démarré.")

        # Chiffres clés : loss, GPU et durée écoulée
        colonne_loss, colonne_gpu, colonne_duree = st.columns(3)
        colonne_loss.metric("Loss (dernière époque)", texte_loss(run), border=True)
        colonne_gpu.metric("GPU", f"GPU {gpu}" if gpu is not None else "-", border=True)
        colonne_duree.metric("Durée", run["duree"], border=True)

        # Lien vers l'étape 4 de la page Apprentissage
        try:
            st.page_link(PAGE_APPRENTISSAGE, label="Voir le suivi")
        except StreamlitAPIException:
            st.caption("Page Apprentissage introuvable (vérifiez PAGE_APPRENTISSAGE).")


# ---------------------------------------------------------------------------
# Historique
# ---------------------------------------------------------------------------

def voir_plus():
    """Affiche 10 entraînements de plus (appelée au clic sur "Voir plus")."""
    st.session_state[CLE_NB_LIGNES] += NB_PAR_PAGE


def afficher_ligne(resume):
    """Affiche une ligne de l'historique."""
    libelle, couleur = LIBELLES[resume["etat"]]
    colonnes = st.columns(LARGEURS_COLONNES, vertical_alignment="center")

    colonnes[0].write(resume["date"])
    colonnes[1].write(resume["dataset"])
    colonnes[2].write(resume["modele"])
    with colonnes[3]:
        st.badge(libelle, color=couleur)
    colonnes[4].write(texte_epoques(resume))
    colonnes[5].write(texte_loss(resume))
    colonnes[6].write(resume["duree"])
    if resume["url_mlflow"]:
        colonnes[7].markdown(f"[Ouvrir]({resume['url_mlflow']})")
    else:
        colonnes[7].write("-")


def section_historique(utilisateur):
    """Tableau des derniers entraînements terminés, avec un bouton "Voir plus"."""
    nb_lignes = st.session_state.setdefault(CLE_NB_LIGNES, NB_PAR_PAGE)

    # On demande une ligne de plus pour savoir s'il en reste à afficher
    resumes = lister_historique(utilisateur, nb_lignes + 1)
    reste_a_voir = len(resumes) > nb_lignes
    resumes = resumes[:nb_lignes]

    if not resumes:
        st.info("Aucun entraînement terminé pour le moment.")
        return

    # Ligne de titres
    for colonne, titre in zip(st.columns(LARGEURS_COLONNES), TITRES_COLONNES):
        colonne.markdown(f"**{titre}**")
    st.divider()

    for resume in resumes:
        afficher_ligne(resume)

    if reste_a_voir:
        st.button("Voir plus", on_click=voir_plus)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

def afficher_accueil():
    """Affiche l'entraînement en cours, puis l'historique des entraînements."""
    utilisateur = st.session_state.get("username")
    if not utilisateur:
        st.warning("Utilisateur inconnu : reconnectez-vous.")
        return

    st.subheader("Entraînement en cours")
    section_en_cours(utilisateur)

    st.subheader("Historique des entraînements")
    section_historique(utilisateur)