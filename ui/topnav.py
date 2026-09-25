"""
modules/topnav.py : en-tête et pied de page de l'application.

L'en-tête (logos, nom de l'appli, menu horizontal, bouton de connexion) est
construit avec les composants natifs de Streamlit (st.columns, st.page_link,
st.button) et un peu de CSS. Il remplace streamlit-option-menu, dont le rendu
dans un cadre à part ne reprenait pas la police de l'appli.

À appeler en haut de chaque page, juste après st.set_page_config(), en
indiquant le libellé de la page courante :

    render_topnav("Accueil")

Le pied de page s'ajoute en bas d'une page avec render_footer().
"""

import base64
from pathlib import Path

import streamlit as st

from modules.auth import get_current_role, is_logged_in, logout_user

# Informations affichées dans l'en-tête et dans le pied de page.
NOM_APPLI = "SpectraVision"
VERSION_APPLI = "v0.1.0"  # à modifier ici uniquement

# Dossier des logos, à la racine du projet.
DOSSIER_ASSETS = Path(__file__).parent.parent / "assets"

# Pages toujours visibles dans le menu : (chemin du fichier, libellé).
# Les chemins sont relatifs au fichier d'entrée de l'appli (app.py).
PAGES_PUBLIQUES = [
    ("app.py", "Accueil"),
    ("pages/1_mode_emploi.py", "Mode d'emploi"),
]

# Page métier ajoutée au menu une fois connecté, selon le rôle.
PAGE_PAR_ROLE = {
    "admin": ("pages/3_admin_dashboard.py", "Administration"),
    "user": ("pages/4_user_dashboard.py", "Mon espace"),
}

PAGE_CONNEXION = "pages/2_connexion.py"

# Style de l'en-tête. La couleur d'accent doit rester identique à
# primaryColor dans .streamlit/config.toml.
CSS = """
:root { --accent: #C8102E; }

/* Le bandeau natif de Streamlit reste en place (voir sidebar.py) : c'est
   lui qui affiche le bouton pour rouvrir la sidebar une fois repliée.
   On le rend juste discret puisque l'appli a son propre en-tête. */
[data-testid="stHeader"] { background: transparent; height: 2.75rem; }

/* Contenu centré avec une largeur maximale, et moins d'espace en haut. */
div[data-testid="stMainBlockContainer"] {
    max-width: 1200px;
    margin: 0 auto;
    padding-top: 1.5rem;
}

/* Logos et nom de l'application. */
.marque { display: flex; align-items: center; gap: 1rem; }
.marque img { height: 44px; width: auto; }
.marque span { font-size: 1.3rem; font-weight: 700; margin-left: 0.5rem; }

/* Liens du menu : texte sombre, sans fond. */
.st-key-entete a { background: transparent !important; justify-content: center; }
.st-key-entete a p {
    color: #333333;
    font-size: 0.95rem;
    text-underline-offset: 6px;
    transition: color 0.15s;
}

/* Survol : texte rouge et léger soulignement. */
.st-key-entete a:hover p {
    color: var(--accent);
    text-decoration: underline;
    text-decoration-thickness: 1px;
}

/* Page courante : texte rouge, en gras, avec un soulignement plus épais. */
.st-key-entete [class*="st-key-nav_actif"] a p {
    color: var(--accent);
    font-weight: 600;
    text-decoration: underline;
    text-decoration-thickness: 2px;
}

/* Nom de l'utilisateur connecté, aligné à droite, à côté du bouton. */
.st-key-entete [data-testid="stCaptionContainer"] { text-align: right; }

/* Pied de page discret. */
.pied-logos { display: flex; align-items: center; gap: 1rem; }
.pied-logos img { height: 28px; width: auto; opacity: 0.85; }
.st-key-pied [data-testid="stCaptionContainer"] { text-align: right; }
"""


@st.cache_data
def _logo_html(nom_fichier: str, texte_alt: str) -> str:
    """
    Retourne une balise <img> contenant le logo encodé en base64.

    L'image est intégrée directement dans le HTML : cela permet de contrôler
    sa taille en CSS et d'éviter le bouton "plein écran" de st.image.
    Retourne une chaîne vide si le fichier est absent.
    """
    chemin = DOSSIER_ASSETS / nom_fichier
    if not chemin.exists():
        return ""

    types_mime = {".jpg": "image/jpeg", ".png": "image/png"}
    type_mime = types_mime.get(chemin.suffix.lower(), "image/png")
    donnees = base64.b64encode(chemin.read_bytes()).decode()
    return f'<img src="data:{type_mime};base64,{donnees}" alt="{texte_alt}">'


def _logos_html() -> str:
    """Retourne le logo LabISEN. Le logo ISEN a été retiré pour gagner de la place."""
    logo_labisen = _logo_html("labisen_logo.png", "Logo LabISEN")
    return logo_labisen


def render_topnav(page_courante: str) -> None:
    """
    Affiche l'en-tête en haut de la page courante.

    Args:
        page_courante: libellé de la page affichée ("Accueil", "Mode d'emploi",
            "Administration" ou "Espace de travail"). Le lien correspondant
            est souligné en rouge. Pour les autres pages (ex : "Connexion"),
            aucun lien n'est souligné.
    """
    st.html(f"<style>{CSS}</style>")

    connecte = is_logged_in()

    # Liens à afficher : les pages publiques, plus la page métier du rôle
    # si l'utilisateur est connecté.
    liens = list(PAGES_PUBLIQUES)
    role = get_current_role()
    if connecte and role in PAGE_PAR_ROLE:
        liens.append(PAGE_PAR_ROLE[role])

    # Largeurs relatives des colonnes : marque, un lien par page,
    # le nom de l'utilisateur (si connecté), puis le bouton.
    poids = [4] + [1.4] * len(liens) + ([1.2] if connecte else []) + [1.0]

    with st.container(key="entete"):
        # On parcourt les colonnes dans l'ordre avec next().
        colonnes = iter(st.columns(poids, vertical_alignment="center"))

        # Logos et nom de l'application.
        with next(colonnes):
            st.html(
                f'<div class="marque">{_logos_html()}<span>{NOM_APPLI}</span></div>'
            )

        # Liens du menu. La clé du conteneur contient "actif" pour la page
        # courante : c'est ce que le CSS utilise pour la souligner.
        for i, (chemin, libelle) in enumerate(liens):
            cle = f"nav_actif_{i}" if libelle == page_courante else f"nav_{i}"
            with next(colonnes):
                with st.container(key=cle):
                    st.page_link(chemin, label=libelle)

        # Bouton de droite : "Déconnexion" (avec le nom) ou "Connexion".
        if connecte:
            with next(colonnes):
                st.caption(f":material/person: {st.session_state.get('username', '')}")
            with next(colonnes):
                if st.button("Déconnexion", key="topnav_deconnexion", width="stretch"):
                    logout_user()
                    st.switch_page(PAGE_CONNEXION)
        else:
            with next(colonnes):
                if st.button(
                    "Connexion", key="topnav_connexion", type="primary", width="stretch"
                ):
                    st.switch_page(PAGE_CONNEXION)

    st.divider()


def render_footer() -> None:
    """Affiche un pied de page discret : les deux logos et la version."""
    st.divider()
    with st.container(key="pied"):
        col_logos, col_version = st.columns([3, 1], vertical_alignment="center")
        with col_logos:
            st.html(f'<div class="pied-logos">{_logos_html()}</div>')
        with col_version:
            st.caption(f"{NOM_APPLI} {VERSION_APPLI}")