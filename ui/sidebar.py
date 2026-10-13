"""
ui/sidebar.py : menu latéral des espaces utilisateur et administrateur.

S'ajoute au menu horizontal du haut (ui/topnav.py) sur les pages
concernées. À appeler après render_topnav() et require_role(), en
indiquant le libellé de la section courante :

    # Espace utilisateur (valeurs par défaut)
    render_sidebar("Acquisition")

    # Espace administrateur
    render_sidebar("Reporting", SECTIONS_ADMIN, "Administration")

Pour ajouter une section : créer la page dans pages/, puis ajouter une
ligne dans la liste de sections correspondante.
"""

import streamlit as st

# Sections du menu utilisateur : (chemin du fichier, libellé, icône Material).
# Les chemins sont relatifs au fichier d'entrée de l'appli (app.py).
SECTIONS_UTILISATEUR = [
    ("pages/4_user_dashboard.py", "Accueil", ":material/home:"),
    ("pages/4a_acquisition.py", "Acquisition", ":material/photo_camera:"),
    ("pages/4b_gestion_bdd.py", "Gestion des BDD", ":material/database:"),
    ("pages/4c_apprentissage.py", "Apprentissage", ":material/model_training:"),
]

# Sections du menu administrateur, même format.
SECTIONS_ADMIN = [
    ("pages/3_admin_dashboard.py", "Accueil", ":material/home:"),
    ("pages/3a_ajout_utilisateur.py", "Ajout utilisateur", ":material/person_add:"),
    ("pages/3b_comptes_utilisateurs.py", "Comptes utilisateurs", ":material/group:"),
    ("pages/3c_reporting.py", "Reporting", ":material/bar_chart:"),
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


def render_sidebar(
    page_courante: str,
    sections: list = SECTIONS_UTILISATEUR,
    titre: str = "Espace de travail",
) -> None:
    """
    Affiche le menu latéral.

    Args:
        page_courante: libellé de la section affichée (par exemple
            "Acquisition" ou "Reporting"). Le lien correspondant est mis
            en avant en rouge.
        sections: liste des sections à afficher (SECTIONS_UTILISATEUR par
            défaut, ou SECTIONS_ADMIN).
        titre: titre affiché en haut du menu.
    """
    st.html(f"<style>{CSS}</style>")

    with st.sidebar:
        st.markdown(f"#### {titre}")

        with st.container(key="menu_lateral"):
            for i, (chemin, libelle, icone) in enumerate(sections):
                # La clé contient "actif" pour la section courante : c'est
                # ce que le CSS utilise pour la mettre en avant.
                cle = f"side_actif_{i}" if libelle == page_courante else f"side_{i}"
                with st.container(key=cle):
                    st.page_link(chemin, label=libelle, icon=icone)