"""
modules/topnav.py : barre de navigation horizontale personnalisée.

Utilise la librairie streamlit-option-menu pour avoir un contrôle précis
sur les couleurs de survol et de sélection (texte rouge souligné), ce que
ne permet pas st.page_link nativement.

À appeler en haut de chaque page de l'appli, juste après
st.set_page_config(), en indiquant le libellé de la page courante.
"""

import streamlit as st
from streamlit_option_menu import option_menu

# Liste des pages du menu : (chemin du fichier, libellé affiché).
# Le chemin est relatif au fichier d'entrée de l'appli (app.py).
# Les pages qui ne font pas partie du menu (ex : tableaux de bord après
# connexion) n'ont pas besoin d'y figurer.
PAGES = [
    ("app.py", "Accueil"),
    ("pages/1_mode_emploi.py", "Mode d'emploi"),
    ("pages/2_connexion.py", "Connexion"),
    # Ajoute ici les futures pages, par exemple :
    # ("pages/3_admin.py", "Admin"),
]

# Couleur d'accent utilisée au survol et pour l'onglet sélectionné.
COULEUR_ACCENT = "#C8102E"

# Police commune à tout le reste de l'appli. Le composant du menu
# s'affiche dans un cadre à part et ne reprend pas automatiquement la
# police de Streamlit, d'où ce réglage explicite.
POLICE_APPLI = "-apple-system, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"


def _naviguer_apres_clic(cle_widget: str = "topnav") -> None:
    """
    Callback appelé uniquement lors d'un vrai clic de l'utilisateur sur le
    menu, jamais lors d'un simple rechargement de page. C'est ce qui évite
    la redirection intempestive vers l'accueil sur les pages (comme les
    tableaux de bord) qui ne font pas partie du menu.
    """
    chemins = {label: path for path, label in PAGES}
    label_choisi = st.session_state[cle_widget]
    st.switch_page(chemins[label_choisi])


def render_topnav(page_courante: str) -> None:
    """
    Affiche le menu horizontal en haut de la page courante.

    Args:
        page_courante: libellé de la page actuellement affichée (doit
            correspondre à un des libellés de PAGES pour être surligné
            au tout premier affichage de la session).
    """
    libelles = [label for _, label in PAGES]
    index_defaut = libelles.index(page_courante) if page_courante in libelles else 0

    option_menu(
        menu_title=None,
        options=libelles,
        icons=[""] * len(libelles),  # aucune icone devant les libelles
        orientation="horizontal",
        default_index=index_defaut,
        key="topnav",
        on_change=_naviguer_apres_clic,
        styles={
            "container": {"padding": "0", "background-color": "transparent"},
            "icon": {"display": "none"},
            "nav-link": {
                "font-family": POLICE_APPLI,
                "font-size": "15px",
                "text-align": "center",
                "color": "#333333",
                "--hover-color": "transparent",
            },
            "nav-link:hover": {
                "color": COULEUR_ACCENT,
                "text-decoration": "underline",
            },
            "nav-link-selected": {
                "background-color": "transparent",
                "color": COULEUR_ACCENT,
                "text-decoration": "underline",
                "font-weight": "600",
            },
        },
    )

    st.divider()