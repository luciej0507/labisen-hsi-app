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

from modules.datasets import (
    chemin_relatif,
    list_folder_contents,
    mettre_a_jour_selection,
)


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


def _retirer_de_la_selection(cle_selection: str, chemin: str) -> None:
    """Retire un chemin de la sélection (bouton Retirer du récapitulatif)."""
    st.session_state[cle_selection] = mettre_a_jour_selection(
        st.session_state[cle_selection], chemin, False
    )


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


def _afficher_niveau(chemin: str, prefixe_cle: str, profondeur: int) -> None:
    """
    Affiche un dossier : une ligne par élément (chevron pour les dossiers,
    case à cocher pour tous). Si un dossier est ouvert, son contenu est
    affiché juste en dessous, décalé d'un cran vers la droite.
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
            # Chevron réservé aux dossiers (les fichiers n'ont pas de bouton)
            if element["est_dossier"]:
                st.button(
                    "",
                    key=f"{prefixe_cle}chevron_{chemin_element}",
                    icon=":material/expand_more:" if est_ouvert else ":material/chevron_right:",
                    type="tertiary",
                    help="Replier ce dossier" if est_ouvert else "Déplier ce dossier",
                    on_click=_sur_bouton_dossier,
                    args=(cle_ouverts, chemin_element),
                )
        with colonne_case:
            # Un "/" final distingue les dossiers des fichiers.
            libelle = element["nom"] + ("/" if element["est_dossier"] else "")
            st.checkbox(
                libelle,
                key=cle_case,
                on_change=_sur_case_modifiee,
                args=(cle_selection, chemin_element, cle_case),
            )

        # Contenu du dossier ouvert, un cran plus à droite
        if element["est_dossier"] and est_ouvert:
            _afficher_niveau(chemin_element, prefixe_cle, profondeur + 1)


def afficher_arborescence_datasets(racine: str, prefixe_cle: str,
                                   deja_autorises: list) -> None:
    """
    Affiche les datasets du serveur sous forme d'arborescence à plat : un
    dossier se déplie ou se replie avec son chevron, et son contenu est
    indenté sous lui. Un récapitulatif des éléments sélectionnés (avec un
    bouton pour retirer chacun d'eux) est affiché sous l'arborescence.

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
    st.session_state.setdefault(cle_selection, set(deja_autorises))
    st.session_state.setdefault(f"{prefixe_cle}ouverts", set())

    _afficher_niveau(racine, prefixe_cle, 0)

    # Récapitulatif de la sélection (chemins affichés sans la racine)
    selection = sorted(st.session_state[cle_selection])
    with st.expander(f"Datasets sélectionnés ({len(selection)})", expanded=True):
        if not selection:
            st.caption("Aucun dataset sélectionné.")
        for chemin_selectionne in selection:
            colonne_nom, colonne_retirer = st.columns([8, 1], vertical_alignment="center")
            with colonne_nom:
                st.text(chemin_relatif(racine, chemin_selectionne))
            with colonne_retirer:
                st.button(
                    "Retirer",
                    key=f"{prefixe_cle}retirer_{chemin_selectionne}",
                    on_click=_retirer_de_la_selection,
                    args=(cle_selection, chemin_selectionne),
                )