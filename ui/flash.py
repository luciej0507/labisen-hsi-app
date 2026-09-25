"""
flash.py : Messages "flash" pour Streamlit.

Un message affiché juste avant un st.rerun() disparait immédiatement, car
le script repart de zéro. Ici, on stocke le message dans st.session_state,
puis on l'affiche au tour suivant, à l'endroit voulu. Il reste visible
jusqu'à la prochaine interaction de l'utilisateur.

Usage :
    flash("success", "Compte modifié.", scope="comptes")
    st.rerun()

    # ... plus haut dans la page, au début de la zone concernée :
    render_flash("comptes")

Le paramètre scope évite qu'un message destiné à un onglet s'affiche dans
un autre.
"""

import streamlit as st

_FLASH_KEY = "_flash_messages"
_LEVELS = ("success", "info", "warning", "error")


def flash(level: str, message: str, scope: str = "default") -> None:
    """Met un message en file d'attente pour le prochain affichage."""
    if level not in _LEVELS:
        raise ValueError("level doit être l'une de ces valeurs : " + ", ".join(_LEVELS))
    st.session_state.setdefault(_FLASH_KEY, []).append((scope, level, message))


def render_flash(scope: str = "default") -> None:
    """Affiche puis retire les messages en attente pour ce scope."""
    pending = st.session_state.get(_FLASH_KEY, [])
    if not pending:
        return

    remaining = []
    for item in pending:
        item_scope, level, message = item
        if item_scope == scope:
            getattr(st, level)(message)
        else:
            remaining.append(item)

    st.session_state[_FLASH_KEY] = remaining