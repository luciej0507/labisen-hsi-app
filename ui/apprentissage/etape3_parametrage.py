"""Interface de l'étape 3 (Paramétrage) de la page Apprentissage.

Logique métier dans modules/apprentissage/etape_parametrage.py.
"""

import streamlit as st

from modules.apprentissage.etape_parametrage import (
    DOCUMENTATIONS,
    FRACTION_PAR_DEFAUT,
    FRACTIONS,
    MODELE_PAR_DEFAUT,
    MODELES,
    PARAMETRES_GENERAUX,
    SPLIT_PAR_DEFAUT,
    SPLITS,
    TITRES_BLOCS,
    TYPE_PAR_DEFAUT,
    TYPES_APPRENTISSAGE,
    construire_config,
    message_labels,
    trier_formats,
)
from modules.apprentissage.etape_patching import (
    libelles_versions,
    trouver_version,
    version_utilisable,
)
from ui.apprentissage import etat
from ui.apprentissage.cache import versions_du_dataset
from ui.apprentissage.styles import css_blocs_parametrage


def champ_hyperparametre(modele, parametre):
    """Affiche le champ d'un hyperparamètre selon son type et retourne sa valeur."""
    # La clé contient le modèle : changer de modèle change aussi les champs
    cle = f"appr_hp_{modele}_{parametre['cle']}"
    libelle = parametre["libelle"]
    type_champ = parametre["type"]
    # Texte de l'infobulle (None = pas d'infobulle)
    aide = parametre.get("aide")

    # Liste déroulante
    if type_champ == "choix":
        options = parametre["options"]
        return st.selectbox(
            libelle, options, index=options.index(parametre["defaut"]),
            key=cle, help=aide,
        )
    # Interrupteur
    if type_champ == "booleen":
        return st.toggle(libelle, value=parametre["defaut"], key=cle, help=aide)
    # Nombre entier ou décimal (le type des bornes suit celui du défaut)
    return st.number_input(
        libelle,
        min_value=parametre["min"],
        max_value=parametre["max"],
        value=parametre["defaut"],
        step=parametre["pas"],
        key=cle,
        help=aide,
    )


def section_approche_modele():
    """Bloc 1 : type d'apprentissage et modèle. Retourne (type, modèle)."""
    # Le conteneur à clé donne la classe CSS qui colore l'expander
    with st.container(key="bloc-bleu"), st.expander(TITRES_BLOCS["modele"], expanded=True):
        types = list(TYPES_APPRENTISSAGE)
        choix_type = st.radio(
            "Type d'apprentissage",
            types,
            index=types.index(TYPE_PAR_DEFAUT),
            horizontal=True,
            key="appr_type",
        )
        type_apprentissage = TYPES_APPRENTISSAGE[choix_type]
        if type_apprentissage == "supervise":
            st.caption(
                "Les modèles disponibles actuellement sont conçus pour "
                "un apprentissage non supervisé."
            )

        modeles = list(MODELES)
        modele = st.selectbox(
            "Modèle anomalib",
            modeles,
            index=modeles.index(MODELE_PAR_DEFAUT),
            key="appr_modele",
        )

    # Un expander ne peut pas être imbriqué dans un autre : la documentation
    # a donc le sien, juste en dessous, replié par défaut (même teinte bleue)
    with st.container(key="bloc-bleu-documentation"), st.expander("Documentation du modèle"):
        st.markdown(DOCUMENTATIONS[modele])
    return type_apprentissage, modele


def section_hyperparametres(modele):
    """Bloc 2 : hyperparamètres du modèle. Retourne un dictionnaire."""
    valeurs = {}
    with st.container(key="bloc-violet"), st.expander(
        TITRES_BLOCS["hyperparametres"], expanded=True
    ):
        for parametre in MODELES[modele]:
            valeurs[parametre["cle"]] = champ_hyperparametre(modele, parametre)
    return valeurs


def section_parametres_generaux():
    """Bloc 3 : paramètres communs à tous les modèles. Retourne un dictionnaire."""
    valeurs = {}
    with st.container(key="bloc-turquoise"), st.expander(
        TITRES_BLOCS["generaux"], expanded=True
    ):
        for parametre in PARAMETRES_GENERAUX:
            # "general" sert uniquement à rendre la clé du champ unique
            valeurs[parametre["cle"]] = champ_hyperparametre("general", parametre)
        if not valeurs["validation"]:
            st.caption("La validation est désactivée : aucune métrique n'est calculée pendant l'entraînement.")
    return valeurs


def section_donnees(type_apprentissage, utilisables):
    """Bloc 4 : split, format de patches et fraction du CSV.

    Retourne (split, format de patches, fraction en pourcentage).
    """
    with st.container(key="bloc-orange"), st.expander(TITRES_BLOCS["donnees"], expanded=True):
        # Ordre des choix : split, puis format de patches, puis fraction
        split = st.radio(
            "Split",
            SPLITS,
            index=SPLITS.index(SPLIT_PAR_DEFAUT),
            horizontal=True,
            key="appr_split",
        )

        # Le format choisi à l'étape précédente est présélectionné
        version = st.session_state.get(etat.VERSION)
        index_format = utilisables.index(version) if version in utilisables else 0
        format_patches = st.selectbox(
            "Format de patches", utilisables, index=index_format, key="appr_format"
        )

        fraction = st.radio(
            "Fraction du CSV",
            FRACTIONS,
            index=FRACTIONS.index(FRACTION_PAR_DEFAUT),
            format_func=lambda f: f"{f} %",
            horizontal=True,
            key="appr_fraction",
        )

        # Rappel du filtrage sur les labels selon le type d'apprentissage
        st.info(message_labels(type_apprentissage))
    return split, format_patches, fraction


def section_validation(config):
    """Valide la configuration au clic."""
    if st.button("Valider la configuration", type="primary"):
        # La configuration est transmise à l'étape suivante, et le format
        # de patches choisi ici devient celui du parcours
        st.session_state[etat.CONFIG] = config
        st.session_state[etat.VERSION] = config["format_patches"]
        st.session_state[etat.MESSAGE] = "Configuration enregistrée."
        st.session_state[etat.ETAPE] = 3
        st.rerun()


def etape_parametrage():
    """Étape 3 : choix du type d'apprentissage, du modèle, des paramètres et des données."""
    st.subheader("Paramétrage")
    # Couleurs des expanders (un bloc par teinte)
    st.markdown(css_blocs_parametrage(), unsafe_allow_html=True)
    st.caption(
        "Choisissez les paramètres de l'entraînement, puis validez la configuration."
    )

    chemin_dataset = st.session_state[etat.DATASET]
    with st.spinner("Recherche des formats de patches disponibles..."):
        versions = versions_du_dataset(chemin_dataset)

    # Serveur injoignable : on ne peut pas proposer de format de patches
    if versions is None:
        st.warning("Serveur injoignable : impossible de lire les formats de patches disponibles.")
        return

    # Seuls les formats dont le split Train est patché peuvent être utilisés
    noms = list(libelles_versions(versions))
    utilisables = [n for n in noms if version_utilisable(trouver_version(versions, n))]
    # Le format w1 est proposé en premier dans le menu
    utilisables = trier_formats(utilisables)
    if not utilisables:
        st.warning(
            "Aucun format de patches utilisable pour ce dataset. "
            "Retournez à l'étape Patching pour en préparer un."
        )
        return

    # Les quatre blocs, dans l'ordre (aucun n'est verrouillé)
    type_apprentissage, modele = section_approche_modele()
    hyperparametres = section_hyperparametres(modele)
    parametres_generaux = section_parametres_generaux()
    split, format_patches, fraction = section_donnees(type_apprentissage, utilisables)

    # Un seul dictionnaire regroupe tous les choix
    config = construire_config(
        type_apprentissage, modele, hyperparametres, parametres_generaux,
        split, format_patches, fraction,
    )
    st.divider()
    section_validation(config)
