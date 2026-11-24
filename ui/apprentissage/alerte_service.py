"""Messages affichés quand le service de calcul est arrêté.

Le "service de calcul" est le worker (worker.py) : c'est lui qui exécute le
patching et les entraînements. Pour les utilisateurs, qui ne connaissent pas
le mot "worker", les messages parlent du "service de calcul".

Si ce service est arrêté, les demandes sont bien enregistrées mais ne
démarrent jamais. Ces messages l'expliquent et disent quoi faire.
"""

import streamlit as st

from modules.etat_gpus import get_etat_worker_collection, worker_est_actif

CONSEIL = "Prévenez l'administrateur de la plateforme."

# Texte destiné à la personne qui gère le serveur
AIDE_ADMINISTRATEUR = (
    "Pour l'administrateur : démarrer le worker sur le serveur, "
    "avec la commande « python worker.py »."
)

# Un message par situation : (niveau, texte).
# Niveaux possibles : "warning" (orange) ou "error" (rouge)
MESSAGES = {
    # Une demande est enregistrée mais n'a pas encore démarré
    "attente": (
        "warning",
        "Le service de calcul est arrêté. Votre demande est bien enregistrée, "
        "mais elle ne démarrera qu'une fois le service relancé. " + CONSEIL,
    ),
    # Un calcul est affiché comme "en cours" mais plus rien ne le fait avancer
    "en_cours": (
        "warning",
        "Le service de calcul ne donne plus de nouvelles. Ce qui s'affiche "
        "ici n'est peut-être plus à jour, et le calcul est peut-être "
        "interrompu. " + CONSEIL,
    ),
    # Avant de lancer un patching
    "lancement_patching": (
        "warning",
        "Le service de calcul est arrêté. Vous pouvez enregistrer votre "
        "demande de patching, mais elle ne démarrera qu'une fois le service "
        "relancé. " + CONSEIL,
    ),
    # Avant de lancer un entraînement : sans le service, pas de GPU connus
    "lancement_entrainement": (
        "error",
        "Le service de calcul est arrêté : l'état des GPU est inconnu et "
        "l'entraînement ne peut pas être lancé pour le moment. " + CONSEIL,
    ),
}


def service_calcul_actif() -> bool:
    """Renvoie True si le service de calcul (le worker) est en vie."""
    return worker_est_actif(get_etat_worker_collection())


def message_service_arrete(situation: str) -> tuple:
    """Renvoie le (niveau, texte) du message à afficher pour une situation."""
    return MESSAGES[situation]


def afficher_alerte_service_arrete(situation: str):
    """Affiche le message correspondant à la situation, suivi de l'aide pour l'administrateur."""
    niveau, texte = message_service_arrete(situation)
    if niveau == "error":
        st.error(texte)
    else:
        st.warning(texte)
    st.caption(AIDE_ADMINISTRATEUR)