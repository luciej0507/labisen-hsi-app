"""
ui/arbre_datasets.py : arborescence des datasets avec cases à cocher.

Utilisée par la page d'ajout d'un utilisateur et par la page de
modification d'un compte. Les deux fonctions publiques sont :

    afficher_arborescence_datasets(racine, prefixe_cle, deja_autorises)
    lire_selection(prefixe_cle)

Chaque formulaire utilise son propre préfixe de clé, ce qui garde sa
sélection indépendante de celle des autres formulaires.
"""

import streamlit as st

from modules.datasets.exploration_dataset import (
    chemin_relatif,
    list_folder_contents,
    mettre_a_jour_selection,
)

# Hauteur (en pixels) de la zone qui contient l'arborescence.
# L'arbre défile à l'intérieur de cette zone si elle est trop petite.
HAUTEUR_ARBRE = 400

# Style qui rend l'arbre plus compact (moins d'espace entre les lignes).
# Il ne s'applique qu'au conteneur dont la clé contient "arbre_datasets_zone".
STYLE_COMPACT = """
<style>
div[class*="arbre_datasets_zone"] [data-testid="stVerticalBlock"] {
    gap: 0.1rem;
}
div[class*="arbre_datasets_zone"] [data-testid="stHorizontalBlock"] {
    gap: 0.25rem;
}
div[class*="arbre_datasets_zone"] button {
    padding: 0;
    min-height: 1.6rem;
}
</style>
"""


def _sur_case_modifiee(cle_selection: str, chemin: str, cle_case: str) -> None:
    """Met à jour la sélection en session quand une case est cochée ou décochée."""
    st.session_state[cle_selection] = mettre_a_jour_selection(
        st.session_state[cle_selection], chemin, st.session_state[cle_case]
    )


def _sur_bouton_dossier(cle_ouverts: str, chemin: str) -> None:
    """Ouvre un dossier s'il est fermé, le ferme sinon."""
    ouverts = st.session_state[cle_ouverts]
    if chemin in ouverts:
        ouverts.remove(chemin)
    else:
        ouverts.add(chemin)


def _sur_tout_replier(cle_ouverts: str) -> None:
    """Referme tous les dossiers dépliés (la sélection n'est pas modifiée)."""
    st.session_state[cle_ouverts] = set()


def _sur_pastilles_modifiees(cle_selection: str, cle_pastilles: str) -> None:
    """
    Met à jour la sélection quand l'admin clique sur une pastille du
    récapitulatif : les pastilles encore actives forment la nouvelle sélection.
    """
    st.session_state[cle_selection] = set(st.session_state[cle_pastilles])


def lire_selection(prefixe_cle: str) -> list:
    """Renvoie la liste triée des chemins cochés pour ce formulaire."""
    return sorted(st.session_state.get(f"{prefixe_cle}selection", set()))


def _colonnes_ligne(profondeur: int):
    """
    Découpe une ligne en un décalage vide, une colonne pour le chevron et
    une colonne pour le contenu. Renvoie (colonne_chevron, colonne_contenu).

    Le total des poids est toujours le même (31) : le décalage d'un niveau
    correspond donc à la largeur d'un chevron, et les éléments d'un dossier
    s'alignent sous le nom de ce dossier.
    """
    profondeur = min(profondeur, 25)
    poids = ([profondeur] if profondeur > 0 else []) + [1, 30 - profondeur]
    colonnes = st.columns(poids, vertical_alignment="center", gap="small")
    return colonnes[-2], colonnes[-1]


def _afficher_niveau(chemin: str, prefixe_cle: str, profondeur: int,
                     recherche: str) -> None:
    """
    Affiche un dossier : une ligne par élément (chevron pour les dossiers,
    case à cocher pour tous). Si un dossier est ouvert, son contenu est
    affiché juste en dessous, décalé d'un cran vers la droite.

    `recherche` est le texte tapé par l'admin (en minuscules, vide s'il n'y
    a pas de recherche). Quand il n'est pas vide, on n'affiche que les
    éléments dont le nom contient ce texte, plus les dossiers déjà ouverts.
    """
    cle_selection = f"{prefixe_cle}selection"
    cle_ouverts = f"{prefixe_cle}ouverts"

    # Un seul niveau est lu sur le serveur à chaque appel
    elements = list_folder_contents(chemin)
    if not elements:
        if profondeur == 0:
            st.info("Aucun dataset trouvé sur le serveur.")
        else:
            _, colonne_contenu = _colonnes_ligne(profondeur)
            colonne_contenu.caption("Dossier vide ou inaccessible.")
        return

    # Filtre de recherche : on garde les noms qui correspondent et les
    # dossiers ouverts (pour ne pas cacher ce que l'admin est en train de lire)
    if recherche:
        elements = [
            e for e in elements
            if recherche in e["nom"].lower()
            or (e["est_dossier"] and e["chemin"] in st.session_state[cle_ouverts])
        ]
        if not elements and profondeur == 0:
            st.caption("Aucun résultat pour cette recherche.")
            return

    for element in elements:
        chemin_element = element["chemin"]
        cle_case = f"{prefixe_cle}case_{chemin_element}"
        est_ouvert = chemin_element in st.session_state[cle_ouverts]

        # L'état de la case est recalculé à partir de la sélection à chaque
        # affichage : ainsi, retirer un élément depuis le récapitulatif
        # décoche aussi sa case dans la liste.
        st.session_state[cle_case] = chemin_element in st.session_state[cle_selection]

        colonne_chevron, colonne_case = _colonnes_ligne(profondeur)
        with colonne_chevron:
            # Chevron réservé aux dossiers (les fichiers n'ont pas de bouton).
            # Pas de paramètre help : l'infobulle restait parfois affichée
            # après un clic.
            if element["est_dossier"]:
                st.button(
                    "",
                    key=f"{prefixe_cle}chevron_{chemin_element}",
                    icon=":material/expand_more:" if est_ouvert else ":material/chevron_right:",
                    type="tertiary",
                    on_click=_sur_bouton_dossier,
                    args=(cle_ouverts, chemin_element),
                )
        with colonne_case:
            # Une icône distingue les dossiers (ouvert ou fermé) des fichiers
            if element["est_dossier"]:
                icone = ":material/folder_open:" if est_ouvert else ":material/folder:"
            else:
                icone = ":material/description:"
            st.checkbox(
                f"{icone} {element['nom']}",
                key=cle_case,
                on_change=_sur_case_modifiee,
                args=(cle_selection, chemin_element, cle_case),
            )

        # Contenu du dossier ouvert, un cran plus à droite
        if element["est_dossier"] and est_ouvert:
            _afficher_niveau(chemin_element, prefixe_cle, profondeur + 1, recherche)


def afficher_arborescence_datasets(racine: str, prefixe_cle: str,
                                   deja_autorises: list) -> None:
    """
    Affiche les datasets du serveur sous forme d'arborescence à plat : un
    dossier se déplie ou se replie avec son chevron, et son contenu est
    indenté sous lui. L'arbre est placé dans une zone à hauteur fixe qui
    défile. Un champ de recherche et un bouton "Tout replier" sont proposés
    au-dessus, et un récapitulatif des éléments sélectionnés (sous forme de
    pastilles sur lesquelles on clique pour retirer un élément) est affiché
    en dessous.

    Le contenu d'un dossier n'est lu sur le serveur que lorsqu'il est
    déplié. La sélection et la liste des dossiers dépliés sont mémorisées
    en session (prefixe_cle + "selection" et prefixe_cle + "ouverts"),
    donc replier un dossier ne fait perdre aucune case cochée.

    Args:
        racine: chemin du dossier racine des datasets sur le serveur.
        prefixe_cle: préfixe des clés de session de ce formulaire.
        deja_autorises: chemins cochés au départ (liste vide pour un ajout).
    """
    cle_selection = f"{prefixe_cle}selection"
    cle_ouverts = f"{prefixe_cle}ouverts"
    st.session_state.setdefault(cle_selection, set(deja_autorises))
    st.session_state.setdefault(cle_ouverts, set())

    # Barre d'outils : recherche à gauche, bouton "Tout replier" à droite
    colonne_recherche, colonne_replier = st.columns(
        [4, 1], vertical_alignment="center"
    )
    with colonne_recherche:
        texte_recherche = st.text_input(
            "Rechercher",
            key=f"{prefixe_cle}recherche",
            placeholder="Rechercher un dossier ou un fichier...",
            label_visibility="collapsed",
        )
    with colonne_replier:
        st.button(
            "Tout replier",
            key=f"{prefixe_cle}tout_replier",
            icon=":material/unfold_less:",
            on_click=_sur_tout_replier,
            args=(cle_ouverts,),
        )

    # Zone de l'arbre : hauteur fixe, avec une barre de défilement
    st.markdown(STYLE_COMPACT, unsafe_allow_html=True)
    with st.container(
        height=HAUTEUR_ARBRE,
        border=True,
        key=f"{prefixe_cle}arbre_datasets_zone",
    ):
        _afficher_niveau(racine, prefixe_cle, 0, texte_recherche.strip().lower())

    st.caption("Cocher un dossier autorise tout son contenu.")

    # Récapitulatif de la sélection, sous forme de pastilles.
    # Cliquer sur une pastille active la désactive, donc retire le dataset.
    selection = sorted(st.session_state[cle_selection])
    with st.expander(f"Datasets sélectionnés ({len(selection)})", expanded=True):
        if not selection:
            st.caption("Aucun dataset sélectionné.")
        else:
            cle_pastilles = f"{prefixe_cle}pastilles"
            # Toutes les pastilles sont actives au départ : on remet leur état
            # à jour à chaque affichage, comme pour les cases de l'arbre.
            st.session_state[cle_pastilles] = list(selection)
            st.pills(
                "Datasets sélectionnés",
                options=selection,
                selection_mode="multi",
                format_func=lambda chemin: chemin_relatif(racine, chemin),
                key=cle_pastilles,
                label_visibility="collapsed",
                on_change=_sur_pastilles_modifiees,
                args=(cle_selection, cle_pastilles),
            )
            st.caption("Cliquer sur une pastille pour retirer le dataset.")