"""
Page Apprentissage : section de l'espace de travail (rôle user).

Parcours en 4 étapes affiché sous forme de frise : Dataset, Patching,
Paramétrage, Lancement et suivi. Cette page ne contient que de l'interface.
La logique (étapes, verrouillage, lecture des datasets, patching) est dans
modules/apprentissage.py.
"""

import pandas as pd
import streamlit as st

from modules.apprentissage.etape_dataset import lister_datasets_complets
from modules.apprentissage.etape_lancement_suivi import (
    TITRE_BLOC_GPU,
    blocs_recapitulatif,
    libelle_gpu,
    lignes_gpus,
    lire_gpus,
)
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
    FORMATS,
    apercu_patching,
    construire_parametres,
    cubes_a_patcher,
    lancer_patching_cube,
    largeur_commune,
    libelles_versions,
    lignes_versions,
    lire_dimensions_dataset,
    lire_versions,
    nom_dossier_format,
    options_split_source,
    splits_a_patcher,
    splits_deja_patches,
    splits_restants,
    trouver_version,
    version_utilisable,
)
from modules.apprentissage.formats import formater_nombre, formater_splits
from modules.apprentissage.frise import (
    ETAPES,
    etape_accessible,
    etapes_validees,
    libelle_etape,
)
from modules.comptes.auth import require_role
from modules.datasets.exploration_dataset import chemin_relatif
from modules.datasets.sftp import DATASETS_REMOTE_PATH
from modules.datasets.stats import calculer_stats
from modules.db_mongo import get_users_collection
from ui.sidebar import render_sidebar
from ui.topnav import configurer_page, render_topnav

# Durée (en secondes) pendant laquelle les lectures sur le serveur sont gardées
DUREE_CACHE = 60

# Couleurs des boutons de la frise pour une étape validée
VERT = "#2e9e5b"
VERT_FONCE = "#1b6b3a"

# Nombre de cartes par rangée à l'étape 1
CARTES_PAR_RANGEE = 3

# Style des cartes. Chaque conteneur créé avec une clé reçoit une classe CSS
# "st-key-<clé>" : on s'en sert pour encadrer la carte et mettre en évidence
# la carte sélectionnée (couleurs semi-transparentes pour les deux thèmes).
STYLE_CARTES = """
<style>
/* Toutes les cartes : cadre gris discret */
div[class*="st-key-carte-"] {
    padding: 0.75rem 1rem;
    border-radius: 0.5rem;
    border: 1px solid rgba(128, 128, 128, 0.35);
}
/* Carte sélectionnée ou validée : bordure marquée et fond léger */
div[class*="st-key-carte-selectionnee-"] {
    border: 2px solid #c8102e;
    background-color: rgba(200, 16, 46, 0.06);
}
/* Bandeau d'en-tête : espacement, coins arrondis et fond vert (état Complet) */
div[class*="st-key-entete-green-"] {
    padding: 0.5rem 0.75rem;
    border-radius: 0.5rem;
    background-color: rgba(33, 195, 84, 0.15);
}
</style>
"""


# ---------------------------------------------------------------------------
# Lectures mises en cache (évitent de relire le serveur à chaque clic)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=DUREE_CACHE, show_spinner=False)
def datasets_complets(username):
    """Retourne les chemins des datasets autorisés dont l'état est Complet."""
    return lister_datasets_complets(get_users_collection(), username)


@st.cache_data(ttl=DUREE_CACHE, show_spinner=False)
def stats_du_dataset(chemin_dataset):
    """Retourne les statistiques d'un dataset (cubes, masques, RGB, splits)."""
    return calculer_stats(chemin_dataset)


@st.cache_data(ttl=DUREE_CACHE, show_spinner=False)
def versions_du_dataset(chemin_dataset):
    """Retourne les versions préparées d'un dataset, ou None si serveur injoignable."""
    return lire_versions(chemin_dataset)


@st.cache_data(ttl=DUREE_CACHE, show_spinner=False)
def dimensions_du_dataset(chemin_dataset):
    """Retourne les dimensions de tous les cubes du dataset, par split."""
    return lire_dimensions_dataset(chemin_dataset)


# ---------------------------------------------------------------------------
# Frise
# ---------------------------------------------------------------------------

def css_etapes_validees(validees):
    """Construit le CSS qui colore en vert les boutons des étapes validées.

    Streamlit ne propose pas de bouton vert : on cible chaque bouton par sa
    clé (classe st-key-frise_N). Une étape validée ET active reçoit en plus
    une bordure plus marquée pour se distinguer des autres étapes vertes.
    """
    regles = ""
    for index, validee in enumerate(validees):
        if not validee:
            continue
        actif = st.session_state["appr_etape"] == index
        bordure = f"3px solid {VERT_FONCE}" if actif else f"1px solid {VERT}"
        regles += (
            f".st-key-frise_{index} button {{"
            f" background-color: {VERT}; color: white; border: {bordure}; }}"
            f".st-key-frise_{index} button:hover {{"
            f" background-color: {VERT_FONCE}; color: white; }}"
        )
    return regles


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
        actif = st.session_state["appr_etape"] == index
        clic = colonne.button(
            libelle_etape(index, validees[index]),
            key=f"frise_{index}",
            type="primary" if actif else "secondary",
            disabled=not etape_accessible(index, validees),
            width="stretch",
        )
        # Clic sur une étape : on la rend active et on recharge la page
        if clic:
            st.session_state["appr_etape"] = index
            st.rerun()


# ---------------------------------------------------------------------------
# Étape 1 : choix du dataset
# ---------------------------------------------------------------------------

def afficher_infos(chemin, cle):
    """Affiche le contenu d'une carte : bandeau, cubes, masques, RGB et splits.

    `cle` rend unique la clé du bandeau (une carte par dataset).
    """
    stats = stats_du_dataset(chemin)
    total = stats["total_cubes"]

    # Bandeau d'en-tête : nom à gauche, badge d'état à droite. Tous les
    # datasets proposés sont à l'état Complet : le bandeau est toujours vert.
    with st.container(key=f"entete-green-{cle}"):
        colonne_nom, colonne_badge = st.columns([3, 2], vertical_alignment="center")
        colonne_nom.markdown("**" + chemin_relatif(DATASETS_REMOTE_PATH, chemin) + "**")
        colonne_badge.badge("Complet", color="green")

    # Deux espaces + retour = saut de ligne
    st.markdown(
        f"Cubes : **{total}**  \n"
        f"Masques : **{stats['annotes']}/{total}**  \n"
        f"Images RGB : **{stats['rgb']}/{total}**"
    )
    st.caption("Splits : " + formater_splits(stats["cubes_par_split"]))


def afficher_carte(chemin, index, selectionnee):
    """Affiche la carte d'un dataset avec son bouton de sélection."""
    # La clé du conteneur donne la classe CSS qui met la carte en évidence
    statut = "selectionnee" if selectionnee else "normale"
    with st.container(key=f"carte-{statut}-{index}"):
        afficher_infos(chemin, index)

        # Le bouton de la carte choisie change de libellé et permet de désélectionner
        clic = st.button(
            "Désélectionner" if selectionnee else "Sélectionner",
            key=f"selection_{index}",
            type="primary" if selectionnee else "secondary",
            width="stretch",
        )
        if clic:
            # Un clic sur la carte choisie annule la sélection, sinon il la choisit
            st.session_state["appr_selection"] = None if selectionnee else chemin
            # Changer de sélection annule une confirmation en attente
            st.session_state["appr_confirmer_changement"] = None
            st.rerun()


def grille_cartes(complets):
    """Affiche les cartes par rangées de CARTES_PAR_RANGEE."""
    selection = st.session_state.get("appr_selection")

    for debut in range(0, len(complets), CARTES_PAR_RANGEE):
        colonnes = st.columns(CARTES_PAR_RANGEE)
        lot = complets[debut:debut + CARTES_PAR_RANGEE]
        # zip s'arrête au plus court : les colonnes en trop restent vides,
        # ce qui garde la même largeur pour toutes les cartes
        for decalage, (colonne, chemin) in enumerate(zip(colonnes, lot)):
            with colonne:
                afficher_carte(chemin, debut + decalage, chemin == selection)


def valider_dataset(chemin):
    """Enregistre le dataset validé et ouvre l'étape suivante.

    Si le dataset change, la version de patches et la configuration sont
    réinitialisées. Valider de nouveau le même dataset ne réinitialise rien.
    """
    if chemin != st.session_state.get("appr_dataset"):
        st.session_state["appr_version"] = None
        st.session_state["appr_config"] = None
    st.session_state["appr_dataset"] = chemin
    st.session_state["appr_confirmer_changement"] = None
    st.session_state["appr_etape"] = 1
    st.rerun()


def demander_confirmation():
    """Affiche l'avertissement de changement de dataset, s'il y en a un en attente."""
    # Contient le chemin du dataset à valider, ou None s'il n'y a rien en attente
    en_attente = st.session_state.get("appr_confirmer_changement")
    if en_attente is None:
        return

    st.warning(
        "Changer de dataset réinitialisera la version de patches choisie "
        "et le paramétrage. Voulez-vous continuer ?"
    )
    col1, col2 = st.columns(2)
    if col1.button("Confirmer le changement", type="primary", width="stretch"):
        valider_dataset(en_attente)
    if col2.button("Annuler", width="stretch"):
        st.session_state["appr_confirmer_changement"] = None
        st.rerun()


def etape_dataset():
    """Étape 1 : choix du dataset par cartes (uniquement ceux à l'état Complet)."""
    st.subheader("Choix du dataset")
    st.markdown(STYLE_CARTES, unsafe_allow_html=True)

    st.caption(
        "Seuls les datasets à l'état Complet sont proposés. "
        "Sélectionnez une carte, puis validez."
    )

    with st.spinner("Recherche des datasets complets..."):
        complets = datasets_complets(st.session_state["username"])

    # Aucun dataset disponible : on informe l'utilisateur
    if not complets:
        st.warning(
            "Aucun dataset à l'état Complet n'est disponible pour votre compte. "
            "Rendez-vous dans la page Gestion des BDD pour en compléter un."
        )
        return

    grille_cartes(complets)

    # Choix en cours (None tant qu'aucune carte n'est sélectionnée)
    selection = st.session_state.get("appr_selection")
    if selection is None:
        st.caption("Aucune carte sélectionnée.")
    else:
        st.caption(
            "Dataset sélectionné : " + chemin_relatif(DATASETS_REMOTE_PATH, selection)
        )

    # Validation : changer de dataset alors qu'une version de patches est déjà
    # choisie demande d'abord confirmation (la version serait réinitialisée)
    if st.button("Valider ce dataset", type="primary", disabled=selection is None):
        valide = st.session_state.get("appr_dataset")
        version = st.session_state.get("appr_version")
        if valide is not None and selection != valide and version is not None:
            st.session_state["appr_confirmer_changement"] = selection
        else:
            valider_dataset(selection)

    demander_confirmation()


# ---------------------------------------------------------------------------
# Étape 2 : patching
# ---------------------------------------------------------------------------

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
        return

    st.markdown(f"**Récapitulatif des formats de patches disponibles ({len(versions)})**")
    st.dataframe(pd.DataFrame(lignes_versions(versions)), hide_index=True, width="stretch")

    # Formats utilisables : le split Train doit être patché pour entraîner
    noms = list(libelles_versions(versions))
    utilisables = [n for n in noms if version_utilisable(trouver_version(versions, n))]
    if not utilisables:
        st.caption(
            "Le split Train n'est pas encore patché pour ces formats : "
            "ils ne peuvent pas servir à l'entraînement. Complétez-en un ci-dessous."
        )

    # Si aucun format n'est encore retenu, le premier utilisable sert de défaut.
    # Il pourra être modifié à l'étape suivante.
    if st.button("Passer à l'étape suivante", type="primary", disabled=not utilisables):
        if st.session_state.get("appr_version") not in utilisables:
            st.session_state["appr_version"] = utilisables[0]
        st.session_state["appr_etape"] = 2
        st.rerun()


def section_nouveau_patching(chemin_dataset, versions):
    """Permet de lancer un patching : format, splits restants, aperçu, lancement."""
    # Repliée quand des versions existent déjà, dépliée sinon
    with st.expander("Nouveau patching", expanded=not versions):
        # Format des patches : un choix parmi les formats fixes
        choix_format = st.radio("Format des patches", list(FORMATS), horizontal=True)
        full_width = st.toggle("Largeur complète (full_width)", value=False)
        if full_width:
            st.caption(
                "En largeur complète, h et sc sont remplacés par la largeur des cubes. "
                "Seuls w et sl du format choisi sont utilisés."
            )

        # Paramètres du format choisi
        format_choisi = FORMATS[choix_format]
        n_lines = format_choisi["n_lines"]
        patch_size = format_choisi["patch_size"]
        stride_lines = format_choisi["stride_lines"]
        stride_cols = format_choisi["stride_cols"]

        # Dimensions de tous les cubes, lues une seule fois pour le dataset
        with st.spinner("Lecture des dimensions des cubes..."):
            dimensions = dimensions_du_dataset(chemin_dataset)

        # En largeur complète, le nom du format contient la largeur des cubes
        largeur = None
        if full_width:
            largeur, probleme = largeur_commune(dimensions)
            if probleme:
                st.warning(probleme)
                return

        parametres = construire_parametres(
            n_lines, patch_size, stride_lines, stride_cols, full_width
        )
        nom_dossier = nom_dossier_format(
            n_lines, patch_size, stride_lines, stride_cols, full_width, largeur
        )
        st.write("Nom du dossier généré :")
        st.code(nom_dossier, language=None)

        # Un format déjà patché n'est pas proposé une seconde fois
        restants = splits_restants(versions, nom_dossier)
        if not restants:
            st.info(
                "Ce format est déjà entièrement patché pour ce dataset. "
                "Il figure dans les formats de patches disponibles ci-dessus."
            )
            return
        deja = splits_deja_patches(restants)
        if deja:
            st.info(
                f"Déjà patchés pour ce format : {', '.join(deja)}. "
                "Seuls les splits restants sont proposés."
            )

        # Split source : un seul split, ou tous ceux qui restent
        choix_split = st.radio(
            "Split source", options_split_source(restants), horizontal=True
        )
        splits = splits_a_patcher(choix_split, restants)

        apercu = section_apercu(dimensions, splits, parametres)
        section_lancement(chemin_dataset, dimensions, splits, parametres, nom_dossier, apercu)


def section_apercu(dimensions, splits, parametres):
    """Affiche le nombre de cubes et de patches estimés. Retourne l'aperçu."""
    apercu = apercu_patching(dimensions, splits, parametres)

    col1, col2 = st.columns(2)
    col1.metric("Cubes à patcher", apercu["nb_cubes"])
    col2.metric("Patches estimés", formater_nombre(apercu["total_patches"]))

    if apercu["nb_cubes"] == 0:
        st.info("Aucun cube trouvé dans le ou les splits choisis (ou serveur injoignable).")
    else:
        st.caption("Par split : " + formater_splits(apercu["patches_par_split"]))
    if apercu["illisibles"]:
        st.warning(
            f"{apercu['illisibles']} cube(s) aux dimensions illisibles : "
            "ils ne sont pas comptés dans l'estimation."
        )
    return apercu


def section_lancement(chemin_dataset, dimensions, splits, parametres, nom_dossier, apercu):
    """Lance le patching avec une barre de progression."""
    # Le bouton est désactivé tant qu'il n'y a aucun cube à patcher
    if not st.button(
        "Lancer le patching", type="primary", disabled=apercu["nb_cubes"] == 0
    ):
        return

    cubes = cubes_a_patcher(dimensions, splits)
    barre = st.progress(0.0)
    with st.status("Patching en cours...", expanded=True) as statut:
        for i, (split, cube) in enumerate(cubes, start=1):
            st.write(f"Traitement de {cube} (split {split})")
            lancer_patching_cube(chemin_dataset, split, cube, parametres)
            barre.progress(i / len(cubes))
        statut.update(label="Patching terminé", state="complete")

    # La liste des versions doit être relue : la nouvelle version y apparaît,
    # et c'est à l'utilisateur de la choisir ensuite
    versions_du_dataset.clear()
    st.session_state["appr_message"] = (
        f"Patching terminé : {len(cubes)} cube(s) traité(s), format {nom_dossier}. "
        "Il figure désormais dans les formats de patches disponibles."
    )
    st.rerun()


def etape_patching():
    """Étape 2 : versions déjà préparées, ou lancement d'un nouveau patching."""
    st.subheader("Patching")
    st.caption(
        "Les cubes doivent être découpés en patches avant l'entraînement. "
        "Consultez les formats de patches disponibles ou lancez un nouveau patching."
    )

    chemin_dataset = st.session_state["appr_dataset"]
    with st.spinner("Recherche des formats de patches disponibles..."):
        versions = versions_du_dataset(chemin_dataset)

    # Serveur injoignable : on ne peut ni lister les formats ni lancer de patching
    if versions is None:
        st.warning("Serveur injoignable : impossible de lire les formats de patches disponibles.")
        return

    section_versions_existantes(versions)
    section_nouveau_patching(chemin_dataset, versions)


# ---------------------------------------------------------------------------
# Étape 3 : paramétrage
# ---------------------------------------------------------------------------

# Teinte de chaque bloc du paramétrage : (composantes RVB, couleur du titre).
# Les couleurs de fond sont semi-transparentes pour les thèmes clair et sombre.
TEINTES = {
    "bleu": ("47, 128, 237", "#2f80ed"),
    "violet": ("142, 91, 214", "#8e5bd6"),
    "turquoise": ("20, 184, 166", "#14b8a6"),
    "orange": ("217, 115, 13", "#d9730d"),
    "vert": ("31, 157, 85", "#1f9d55"),
}


def css_blocs_parametrage():
    """Construit le CSS qui colore les expanders du paramétrage.

    Chaque expander est placé dans un conteneur de clé "bloc-<teinte>" qui
    reçoit la classe CSS "st-key-bloc-<teinte>". On colore ensuite le cadre
    de l'expander (details) et le texte de son titre (summary).
    Les teintes sont repérées par préfixe : "bloc-bleu" et
    "bloc-bleu-documentation" partagent donc la même couleur.
    """
    regles = ""
    for nom, (rvb, couleur) in TEINTES.items():
        bloc = f'div[class*="st-key-bloc-{nom}"]'
        regles += (
            # Cadre coloré de l'expander (sans fond)
            f"{bloc} details {{ border: 1px solid rgba({rvb}, 0.45); }}"
            # Titre (et flèche d'ouverture) en couleur et en gras
            f"{bloc} summary, {bloc} summary * {{"
            f" color: {couleur}; font-weight: 600; }}"
        )
    return f"<style>{regles}</style>"


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
        version = st.session_state.get("appr_version")
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


def section_validation(config):
    """Valide la configuration au clic."""
    if st.button("Valider la configuration", type="primary"):
        # La configuration est transmise à l'étape suivante, et le format
        # de patches choisi ici devient celui du parcours
        st.session_state["appr_config"] = config
        st.session_state["appr_version"] = config["format_patches"]
        st.session_state["appr_message"] = "Configuration enregistrée."
        st.session_state["appr_etape"] = 3
        st.rerun()


def etape_parametrage():
    """Étape 3 : choix du type d'apprentissage, du modèle, des paramètres et des données."""
    st.subheader("Paramétrage")
    # Couleurs des expanders (un bloc par teinte)
    st.markdown(css_blocs_parametrage(), unsafe_allow_html=True)
    st.caption(
        "Choisissez les paramètres de l'entraînement, puis validez la configuration."
    )

    chemin_dataset = st.session_state["appr_dataset"]
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


# ---------------------------------------------------------------------------
# Étape 4 : lancement et suivi (ébauche)
# ---------------------------------------------------------------------------

# Nombre de cartes par rangée dans le récapitulatif de l'étape 4
CARTES_RECAP_PAR_RANGEE = 2


def css_cartes_recapitulatif():
    """Construit le CSS qui encadre les cartes du récapitulatif.

    Chaque carte est un conteneur de clé "recap-<teinte>" qui reçoit la classe
    CSS "st-key-recap-<teinte>". La bordure prend la même couleur que le titre
    du bloc, sans fond coloré.
    """
    regles = ""
    for nom, (rvb, couleur) in TEINTES.items():
        regles += (
            f'div[class*="st-key-recap-{nom}"] {{'
            f" border: 1px solid {couleur};"
            " border-radius: 0.5rem; padding: 0.75rem 1rem; }"
        )
    return f"<style>{regles}</style>"


def bloc_recapitulatif(titre, teinte, lignes):
    """Affiche une carte du récapitulatif : titre coloré, puis une ligne nom / valeur par choix."""
    couleur = TEINTES[teinte][1]
    # La clé du conteneur donne la classe CSS qui dessine la bordure colorée
    with st.container(key=f"recap-{teinte}"):
        st.markdown(
            f'<span style="color:{couleur}; font-weight:600">{titre}</span>',
            unsafe_allow_html=True,
        )
        # Une ligne par choix : le nom en gris discret, la valeur en gras
        for nom, valeur in lignes:
            colonne_nom, colonne_valeur = st.columns([3, 2])
            colonne_nom.caption(nom)
            colonne_valeur.markdown(f"**{valeur}**")


def section_recapitulatif(config):
    """Rappelle la configuration validée à l'étape 3, en grille de cartes 2 x 2."""
    st.markdown("**Récapitulatif de la configuration**")
    st.markdown(css_cartes_recapitulatif(), unsafe_allow_html=True)

    blocs = blocs_recapitulatif(config)
    # Les cartes sont posées par rangées de deux, dans l'ordre des expanders
    for debut in range(0, len(blocs), CARTES_RECAP_PAR_RANGEE):
        colonnes = st.columns(CARTES_RECAP_PAR_RANGEE)
        lot = blocs[debut:debut + CARTES_RECAP_PAR_RANGEE]
        for colonne, (titre, teinte, lignes) in zip(colonnes, lot):
            with colonne:
                bloc_recapitulatif(titre, teinte, lignes)


def etape_lancement():
    """Étape 4 : rappel de la configuration, choix du GPU et lancement."""
    st.subheader("Lancement et suivi")
    # Couleurs des expanders (celle du bloc GPU)
    st.markdown(css_blocs_parametrage(), unsafe_allow_html=True)

    # Cette étape n'est accessible qu'une fois la configuration validée
    config = st.session_state["appr_config"]
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


# ---------------------------------------------------------------------------
# Page principale
# ---------------------------------------------------------------------------

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
    st.session_state.setdefault("appr_etape", 0)
    st.session_state.setdefault("appr_dataset", None)
    st.session_state.setdefault("appr_version", None)
    st.session_state.setdefault("appr_config", None)

    validees = etapes_validees(
        st.session_state["appr_dataset"],
        st.session_state["appr_version"],
        st.session_state["appr_config"],
    )
    frise(validees)
    st.divider()

    # Message laissé par l'action précédente (affiché une seule fois)
    message = st.session_state.pop("appr_message", None)
    if message:
        st.success(message)

    # Affichage de l'étape active
    etape = st.session_state["appr_etape"]
    if etape == 0:
        etape_dataset()
    elif etape == 1:
        etape_patching()
    elif etape == 2:
        etape_parametrage()
    else:
        etape_lancement()


main()