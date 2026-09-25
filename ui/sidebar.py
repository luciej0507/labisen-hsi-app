"""
modules/sidebar.py : menu latéral de l'espace utilisateur.

S'ajoute au menu horizontal du haut (modules/topnav.py) sur les pages de
l'espace utilisateur. À appeler après render_topnav() et require_role(),
en indiquant le libellé de la section courante :

    render_sidebar("Acquisition")

Pour ajouter une section : créer la page dans pages/, puis ajouter une
ligne dans SECTIONS_UTILISATEUR.
"""

import streamlit as st

# Sections du menu : (chemin du fichier, libellé, icône Material).
# Les chemins sont relatifs au fichier d'entrée de l'appli (app.py).
SECTIONS_UTILISATEUR = [
    ("pages/4_user_dashboard.py", "Accueil", ":material/home:"),
    ("pages/4a_acquisition.py", "Acquisition", ":material/photo_camera:"),
    ("pages/4b_gestion_bdd.py", "Gestion des BDD", ":material/database:"),
    ("pages/4c_apprentissage.py", "Apprentissage", ":material/model_training:"),
]

# Style du menu latéral. La variable --accent est définie dans topnav.py.
CSS = """
/* Liens du menu : texte sombre, rouge au survol. */
.st-key-menu_lateral a p { color: #333333; font-size: 0.95rem; }
.st-key-menu_lateral a:hover p { color: var(--accent); }

/* Section courante : texte rouge en gras et liseré rouge à gauche. */
.st-key-menu_lateral [class*="side_actif"] a { border-left: 3px solid var(--accent); }
.st-key-menu_lateral [class*="side_actif"] a p { color: var(--accent); font-weight: 600; }
"""


def render_sidebar(page_courante: str) -> None:
    """
    Affiche le menu latéral de l'espace utilisateur.

    Args:
        page_courante: libellé de la section affichée ("Accueil",
            "Acquisition", "Gestion des BDD" ou "Apprentissage"). Le lien
            correspondant est mis en avant en rouge.
    """
    st.html(f"<style>{CSS}</style>")

    with st.sidebar:
        st.markdown("#### Espace de travail")

        with st.container(key="menu_lateral"):
            for i, (chemin, libelle, icone) in enumerate(SECTIONS_UTILISATEUR):
                # La clé contient "actif" pour la section courante : c'est
                # ce que le CSS utilise pour la mettre en avant.
                cle = f"side_actif_{i}" if libelle == page_courante else f"side_{i}"
                with st.container(key=cle):
                    st.page_link(chemin, label=libelle, icon=icone)