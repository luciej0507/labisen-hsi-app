"""Interface de l'étape 2 (Patching) de la page Apprentissage.

Logique métier dans modules/apprentissage/etape_patching.py.
"""

from pathlib import Path

import pandas as pd
import streamlit as st

from modules.apprentissage.etape_patching import (
    annuler_patching,
    apercu_patching,
    charger_formats,
    chemin_journal,
    effacer_suivi,
    etat_job,
    formats_a_patcher,
    formats_choisis,
    lancer_patching,
    largeur_commune,
    libelles_versions,
    lignes_versions,
    options_split_source,
    splits_a_patcher,
    splits_deja_patches,
    splits_restants_formats,
    trouver_version,
    version_utilisable,
)
from modules.apprentissage.formats import formater_nombre
from ui.apprentissage import etat
from ui.apprentissage.cache import dimensions_du_dataset, versions_du_dataset

# Intervalle (en secondes) de rafraîchissement de l'avancement du patching
DELAI_SUIVI = 2

# Image qui explique les formats de patches, chemin relatif à la racine du projet
IMAGE_FORMATS = Path("assets/formats_patches.png")


def expander_formats():
    """Affiche le menu déroulant (replié) qui explique les formats de patches."""
    with st.expander("Comprendre les formats de patches"):
        st.caption(
            "Illustration sur un cube de 900 x 1000 pixels avec 300 bandes spectrales : "
            "les dimensions de vos cubes peuvent être différentes, mais le principe reste le même."
        )
        # L'image est lue dans le dossier assets de la racine du projet
        if IMAGE_FORMATS.exists():
            st.image(str(IMAGE_FORMATS), width="stretch")
        else:
            st.caption("Illustration indisponible.")


def section_versions_existantes(versions):
    """Affiche le récapitulatif des formats de patches disponibles.

    Le choix du format se fait à l'étape suivante : ici, l'utilisateur
    consulte les formats et passe à l'étape d'après.
    """
    if not versions:
        st.info(
            "Aucun format de patches disponible pour ce dataset. "
            "Lancez un nouveau patching ci-dessous."
        )
        # L'explication des formats aide aussi à choisir celui à patcher
        expander_formats()
        return

    st.markdown(f"**Récapitulatif des formats de patches disponibles ({len(versions)})**")
    st.caption(
        "Les colonnes Train, Test et Val indiquent les fichiers CSV disponibles "
        "pour chaque split : chaque CSV contient une fraction des données totales "
        "(par exemple 10 % ou 100 %)."
    )
    st.dataframe(pd.DataFrame(lignes_versions(versions)), hide_index=True, width="stretch")

    # Explication des noms de formats, repliée par défaut
    expander_formats()

    # Formats utilisables : le split Train doit être patché pour entraîner
    noms = list(libelles_versions(versions))
    utilisables = [n for n in noms if version_utilisable(trouver_version(versions, n))]
    if not utilisables:
        st.caption(
            "Le split Train n'est pas encore patché pour ces formats : "
            "ils ne peuvent pas servir à l'entraînement. Complétez-en un ci-dessous."
        )
    else:
        # Au moins un format est utilisable : l'utilisateur peut avancer
        st.info(
            "Les formats de patches nécessaires sont déjà prêts. "
            "Vous pouvez passer directement à l'étape suivante."
        )

    # Si aucun format n'est encore retenu, le premier utilisable sert de défaut.
    # Il pourra être modifié à l'étape suivante.
    if st.button("Passer à l'étape suivante", type="primary", disabled=not utilisables):
        if st.session_state.get(etat.VERSION) not in utilisables:
            st.session_state[etat.VERSION] = utilisables[0]
        st.session_state[etat.ETAPE] = 2
        st.rerun()


def section_nouveau_patching(chemin_dataset, versions, job_actif):
    """Permet de lancer un patching : formats, splits restants, aperçu, lancement.

    Plusieurs formats peuvent être choisis : ils sont patchés en un seul
    lancement. `job_actif` vaut True si un patching tourne déjà pour ce
    dataset : le bouton de lancement est alors désactivé.
    """
    # Repliée quand des versions existent déjà, dépliée sinon
    with st.expander("Nouveau patching", expanded=not versions):
        # Catalogue des formats, lu dans config.yaml
        try:
            catalogue = charger_formats()
        except (OSError, ValueError) as erreur:
            st.error(f"Impossible de lire le catalogue des formats : {erreur}")
            return

        # Un ou plusieurs formats parmi ceux du catalogue
        libelles = st.multiselect("Formats des patches", list(catalogue))
        full_width = st.toggle("Largeur complète (full_width)", value=False)
        if full_width:
            st.caption(
                "En largeur complète, h et sc sont remplacés par la largeur des cubes. "
                "Seuls w et sl de chaque format choisi sont utilisés."
            )
        if not libelles:
            st.info("Choisissez au moins un format de patches.")
            return

        # Dimensions de tous les cubes, lues une seule fois pour le dataset
        with st.spinner("Lecture des dimensions des cubes..."):
            dimensions = dimensions_du_dataset(chemin_dataset)

        # En largeur complète, le nom des dossiers contient la largeur des cubes
        largeur = None
        if full_width:
            largeur, probleme = largeur_commune(dimensions)
            if probleme:
                st.warning(probleme)
                return

        choisis = formats_choisis(catalogue, libelles, full_width, largeur)
        st.write("Dossiers générés :")
        st.code("\n".join(f["nom_dossier"] for f in choisis), language=None)

        # Un format déjà entièrement patché n'est pas proposé une seconde fois
        a_patcher = formats_a_patcher(versions, choisis)
        ignores = [f["nom_dossier"] for f in choisis if f not in a_patcher]
        if ignores:
            st.info(
                f"Déjà entièrement patchés (ignorés) : {', '.join(ignores)}. "
                "Ils figurent dans les formats de patches disponibles ci-dessus."
            )
        if not a_patcher:
            return

        # Splits restants : ceux à patcher pour au moins un des formats
        restants = splits_restants_formats(versions, a_patcher)
        deja = splits_deja_patches(restants)
        if deja:
            st.info(
                f"Déjà patchés pour tous les formats choisis : {', '.join(deja)}. "
                "Seuls les splits restants sont proposés."
            )

        # Split source : un seul split, ou tous ceux qui restent
        choix_split = st.radio(
            "Split source", options_split_source(restants), horizontal=True
        )
        splits = splits_a_patcher(choix_split, restants)

        apercu = section_apercu(dimensions, versions, a_patcher, splits)
        section_lancement(chemin_dataset, splits, a_patcher, full_width, apercu, job_actif)


def section_apercu(dimensions, versions, formats, splits):
    """Affiche le nombre de cubes et de patches estimés. Retourne l'aperçu."""
    apercu = apercu_patching(dimensions, versions, formats, splits)

    col1, col2 = st.columns(2)
    col1.metric("Cubes à patcher", apercu["nb_cubes"])
    col2.metric("Patches estimés", formater_nombre(apercu["total_patches"]))

    if apercu["nb_cubes"] == 0:
        st.info("Aucun cube trouvé dans le ou les splits choisis (ou serveur injoignable).")
    else:
        st.caption(
            "Par format : "
            + ", ".join(
                f"{libelle} ({formater_nombre(nombre)})"
                for libelle, nombre in apercu["patches_par_format"].items()
            )
        )
    if apercu["illisibles"]:
        st.warning(
            f"{apercu['illisibles']} cube(s) aux dimensions illisibles : "
            "ils ne sont pas comptés dans l'estimation."
        )
    return apercu


def bouton_annulation(chemin_dataset):
    """Affiche le bouton d'annulation du patching, avec une confirmation."""
    # Premier clic : on demande confirmation
    if not st.session_state.get(etat.CONFIRMER_ANNULATION):
        if st.button("Annuler le patching", key="annuler_patching"):
            st.session_state[etat.CONFIRMER_ANNULATION] = True
            # Recharge seulement le fragment, pour afficher la confirmation
            st.rerun(scope="fragment")
        return

    st.warning(
        "Le split en cours devra être refait. Les splits déjà terminés sont "
        "conservés. Voulez-vous annuler le patching ?"
    )
    col1, col2 = st.columns(2)
    if col1.button("Confirmer l'annulation", type="primary", key="confirmer_annulation"):
        annuler_patching(chemin_dataset)
        st.session_state[etat.CONFIRMER_ANNULATION] = False
        # Des splits ont pu être terminés avant l'annulation : on relit les formats
        versions_du_dataset.clear()
        st.rerun()
    if col2.button("Continuer le patching", key="garder_patching"):
        st.session_state[etat.CONFIRMER_ANNULATION] = False
        st.rerun(scope="fragment")


@st.fragment(run_every=DELAI_SUIVI)
def fragment_suivi(chemin_dataset):
    """Affiche l'avancement du patching, mis à jour toutes les DELAI_SUIVI secondes.

    Seul ce fragment est rechargé, pas toute la page. Dès que le patching
    n'est plus en cours, on relit les formats et on recharge toute la page.
    """
    suivi = etat_job(chemin_dataset)
    if suivi is None or suivi["etat"] != "en cours":
        versions_du_dataset.clear()
        st.rerun()

    total = suivi["cubes_total"]
    faits = suivi["cubes_faits"]
    # Tant que le script démarre, le total est inconnu (0)
    fraction = faits / total if total else 0.0
    texte = f"{faits}/{total} cubes" if total else "Préparation en cours..."

    st.markdown(f"Format(s) : **{suivi['format'] or '...'}**")
    st.progress(fraction, text=texte)
    if suivi["cube_courant"]:
        st.caption(f"Cube en cours : {suivi['cube_courant']}")
    bouton_annulation(chemin_dataset)


def section_suivi(chemin_dataset):
    """Affiche l'état du dernier patching. Retourne True s'il est en cours."""
    suivi = etat_job(chemin_dataset)
    if suivi is None:
        return False

    etat_patching = suivi["etat"]
    if etat_patching == "en cours":
        st.markdown("**Patching en cours**")
        st.caption(
            "Le patching tourne en arrière-plan : vous pouvez changer d'étape "
            "ou fermer la page, il continue."
        )
        fragment_suivi(chemin_dataset)
        return True

    # Patching fini : résultat affiché jusqu'à ce que l'utilisateur le masque
    if etat_patching == "termine":
        st.success(f"Dernier patching terminé : {suivi['message']}.")
    elif etat_patching == "annule":
        st.warning(
            "Le dernier patching a été annulé. "
            "Les splits non terminés restent à patcher."
        )
    else:
        # Erreur du script ou processus disparu
        st.error(f"Le dernier patching a échoué : {suivi['message']}")
        st.caption(f"Journal complet : {chemin_journal(chemin_dataset)}")
    if st.button("Masquer ce message", key="masquer_suivi"):
        effacer_suivi(chemin_dataset)
        st.rerun()
    return False


def section_lancement(chemin_dataset, splits, formats, full_width, apercu, job_actif):
    """Lance le patching en arrière-plan : la page reste utilisable.

    `formats` : formats à patcher (voir formats_choisis). Le script reçoit
    leurs noms dans le catalogue et retrouve les paramètres dans config.yaml.
    """
    if job_actif:
        st.info(
            "Un patching est déjà en cours pour ce dataset : "
            "attendez sa fin ou annulez-le ci-dessus."
        )

    # Désactivé s'il n'y a aucun cube à patcher, ou si un patching tourne déjà
    if not st.button(
        "Lancer le patching",
        type="primary",
        disabled=apercu["nb_cubes"] == 0 or job_actif,
    ):
        return

    try:
        noms_formats = [f["nom_catalogue"] for f in formats]
        lancer_patching(chemin_dataset, splits, noms_formats, full_width)
    except OSError as erreur:
        st.error(f"Impossible de lancer le patching : {erreur}")
        return

    noms_dossiers = ", ".join(f["nom_dossier"] for f in formats)
    st.session_state[etat.CONFIRMER_ANNULATION] = False
    st.session_state[etat.MESSAGE] = (
        f"Patching lancé en arrière-plan, format(s) {noms_dossiers}. "
        "Suivez son avancement en haut de l'étape."
    )
    st.rerun()


def etape_patching():
    """Étape 2 : versions déjà préparées, ou lancement d'un nouveau patching."""
    st.subheader("Patching")
    st.caption(
        "Les cubes doivent être découpés en patches avant l'entraînement. "
        "Consultez les formats de patches disponibles ou lancez un nouveau patching."
    )

    chemin_dataset = st.session_state[etat.DATASET]
    with st.spinner("Recherche des formats de patches disponibles..."):
        versions = versions_du_dataset(chemin_dataset)

    # Serveur injoignable : on ne peut ni lister les formats ni lancer de patching
    if versions is None:
        st.warning("Serveur injoignable : impossible de lire les formats de patches disponibles.")
        return

    # Avancement du patching (affiché en haut pour rester visible), puis le reste
    job_actif = section_suivi(chemin_dataset)
    section_versions_existantes(versions)
    section_nouveau_patching(chemin_dataset, versions, job_actif)