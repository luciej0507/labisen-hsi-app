"""
tests/jobs/test_jobs.py : tests de modules/jobs.py (file d'attente MongoDB).

Aucune connexion réelle n'est ouverte : on utilise une fausse collection
mongomock (fixture "jobs" du fichier conftest.py voisin).
"""

import pytest
from bson import ObjectId

from modules import jobs as file_jobs


def nouveau_job(jobs, type_job=file_jobs.TYPE_PATCHING, **options):
    """Crée un job avec des paramètres bidons et renvoie son identifiant."""
    return file_jobs.creer_job(jobs, type_job, {"exemple": 1}, **options)


# ---------------------------------------------------------------------------
# Création et lecture
# ---------------------------------------------------------------------------

def test_creer_job_remplit_les_champs_par_defaut(jobs):
    """Un job neuf est "en attente", sans arrêt demandé et sans date de fin."""
    job_id = nouveau_job(jobs, utilisateur="alice", gpu=2, cle="/data/avoine")

    job = jobs.find_one({"_id": job_id})
    assert job["type"] == file_jobs.TYPE_PATCHING
    assert job["etat"] == file_jobs.EN_ATTENTE
    assert job["parametres"] == {"exemple": 1}
    assert job["utilisateur"] == "alice"
    assert job["gpu"] == 2
    assert job["cle"] == "/data/avoine"
    assert job["arret_demande"] is False
    assert job["pid"] is None
    assert job["termine_le"] is None
    assert job["cree_le"] is not None


def test_creer_job_refuse_un_type_inconnu(jobs):
    """Un type de job inconnu est refusé et rien n'est enregistré."""
    with pytest.raises(ValueError):
        file_jobs.creer_job(jobs, "cuisine", {})

    assert jobs.count_documents({}) == 0


def test_lire_job_accepte_un_identifiant_en_texte(jobs):
    """L'identifiant peut être donné sous forme de texte (st.session_state)."""
    job_id = nouveau_job(jobs)

    assert file_jobs.lire_job(jobs, str(job_id))["_id"] == job_id
    assert file_jobs.lire_job(jobs, job_id)["_id"] == job_id


def test_lire_job_inconnu_ou_invalide_renvoie_none(jobs):
    """Un identifiant inexistant ou mal formé ne provoque pas d'erreur."""
    assert file_jobs.lire_job(jobs, ObjectId()) is None
    assert file_jobs.lire_job(jobs, "pas un identifiant") is None
    assert file_jobs.lire_job(jobs, None) is None


def test_dernier_job_renvoie_le_plus_recent_de_la_cible(jobs):
    """dernier_job regarde le type et, si on la donne, la cible (cle)."""
    nouveau_job(jobs, cle="/data/avoine")
    recent = nouveau_job(jobs, cle="/data/avoine")
    autre_cible = nouveau_job(jobs, cle="/data/ble")

    assert file_jobs.dernier_job(jobs, file_jobs.TYPE_PATCHING, "/data/avoine")["_id"] == recent
    assert file_jobs.dernier_job(jobs, file_jobs.TYPE_PATCHING, "/data/ble")["_id"] == autre_cible
    assert file_jobs.dernier_job(jobs, file_jobs.TYPE_PATCHING)["_id"] == autre_cible
    assert file_jobs.dernier_job(jobs, file_jobs.TYPE_ENTRAINEMENT) is None


def test_existe_job_actif(jobs):
    """Un job en attente ou en cours est actif, un job fini ne l'est plus."""
    assert file_jobs.existe_job_actif(jobs, file_jobs.TYPE_PATCHING, "/data/avoine") is False

    job_id = nouveau_job(jobs, cle="/data/avoine")
    assert file_jobs.existe_job_actif(jobs, file_jobs.TYPE_PATCHING, "/data/avoine") is True
    # Une autre cible n'est pas concernée
    assert file_jobs.existe_job_actif(jobs, file_jobs.TYPE_PATCHING, "/data/ble") is False
    # Ni un autre type
    assert file_jobs.existe_job_actif(jobs, file_jobs.TYPE_ENTRAINEMENT, "/data/avoine") is False

    file_jobs.terminer_job(jobs, job_id, file_jobs.TERMINE)
    assert file_jobs.existe_job_actif(jobs, file_jobs.TYPE_PATCHING, "/data/avoine") is False


def test_lister_jobs_filtre_et_trie(jobs):
    """Les jobs sont listés du plus récent au plus ancien, avec filtres."""
    premier = nouveau_job(jobs)
    deuxieme = nouveau_job(jobs, file_jobs.TYPE_ENTRAINEMENT)
    troisieme = nouveau_job(jobs)
    file_jobs.terminer_job(jobs, premier, file_jobs.TERMINE)

    tous = [j["_id"] for j in file_jobs.lister_jobs(jobs)]
    assert tous == [troisieme, deuxieme, premier]

    patchings = [j["_id"] for j in file_jobs.lister_jobs(jobs, type_job=file_jobs.TYPE_PATCHING)]
    assert patchings == [troisieme, premier]

    termines = [j["_id"] for j in file_jobs.lister_jobs(jobs, etats=(file_jobs.TERMINE,))]
    assert termines == [premier]

    assert len(file_jobs.lister_jobs(jobs, limite=2)) == 2


# ---------------------------------------------------------------------------
# Réservation (côté worker)
# ---------------------------------------------------------------------------

def test_reserver_sur_une_file_vide_renvoie_none(jobs):
    """Sans job en attente, il n'y a rien à réserver."""
    assert file_jobs.reserver_prochain_job(jobs) is None


def test_reserver_passe_le_job_en_cours(jobs):
    """Le job réservé est renvoyé à l'état "en cours", avec sa date de départ."""
    job_id = nouveau_job(jobs)

    job = file_jobs.reserver_prochain_job(jobs)

    assert job["_id"] == job_id
    assert job["etat"] == file_jobs.EN_COURS
    assert job["demarre_le"] is not None
    # L'état est bien enregistré en base, pas seulement dans la réponse
    assert jobs.find_one({"_id": job_id})["etat"] == file_jobs.EN_COURS


def test_reserver_prend_les_jobs_dans_l_ordre_d_arrivee(jobs):
    """Le plus ancien job est servi en premier."""
    premier = nouveau_job(jobs)
    deuxieme = nouveau_job(jobs)

    assert file_jobs.reserver_prochain_job(jobs)["_id"] == premier
    assert file_jobs.reserver_prochain_job(jobs)["_id"] == deuxieme
    assert file_jobs.reserver_prochain_job(jobs) is None


def test_reserver_ne_prend_jamais_deux_fois_le_meme_job(jobs):
    """Un job déjà réservé n'est plus proposé."""
    nouveau_job(jobs)

    assert file_jobs.reserver_prochain_job(jobs) is not None
    assert file_jobs.reserver_prochain_job(jobs) is None


def test_reserver_ignore_les_jobs_annules(jobs):
    """Un job annulé avant son démarrage n'est jamais exécuté."""
    job_id = nouveau_job(jobs)
    file_jobs.demander_arret(jobs, job_id)

    assert file_jobs.reserver_prochain_job(jobs) is None


# ---------------------------------------------------------------------------
# Arrêt
# ---------------------------------------------------------------------------

def test_demander_arret_d_un_job_en_attente_l_annule_tout_de_suite(jobs):
    """Un job qui n'a pas démarré passe directement à "annule"."""
    job_id = nouveau_job(jobs)

    assert file_jobs.demander_arret(jobs, job_id) is True

    job = jobs.find_one({"_id": job_id})
    assert job["etat"] == file_jobs.ANNULE
    assert job["termine_le"] is not None


def test_demander_arret_d_un_job_en_cours_pose_la_demande(jobs):
    """Pour un job en cours, c'est au worker d'arrêter le calcul."""
    job_id = nouveau_job(jobs)
    file_jobs.reserver_prochain_job(jobs)

    assert file_jobs.demander_arret(jobs, job_id) is True

    job = jobs.find_one({"_id": job_id})
    assert job["etat"] == file_jobs.EN_COURS  # pas encore arrêté
    assert job["arret_demande"] is True
    assert file_jobs.arret_est_demande(jobs, job_id) is True


def test_demander_arret_d_un_job_fini_ne_change_rien(jobs):
    """Un job déjà terminé ne peut plus être arrêté."""
    job_id = nouveau_job(jobs)
    file_jobs.reserver_prochain_job(jobs)
    file_jobs.terminer_job(jobs, job_id, file_jobs.TERMINE)

    assert file_jobs.demander_arret(jobs, job_id) is False
    assert file_jobs.arret_est_demande(jobs, job_id) is False
    assert jobs.find_one({"_id": job_id})["etat"] == file_jobs.TERMINE


def test_demander_arret_identifiant_invalide(jobs):
    """Un identifiant invalide ou inconnu renvoie False sans erreur."""
    assert file_jobs.demander_arret(jobs, "n'importe quoi") is False
    assert file_jobs.demander_arret(jobs, ObjectId()) is False
    assert file_jobs.arret_est_demande(jobs, ObjectId()) is False


# ---------------------------------------------------------------------------
# Mise à jour et fin
# ---------------------------------------------------------------------------

def test_mettre_a_jour_modifie_les_champs_et_rafraichit_maj_le(jobs):
    """mettre_a_jour change les champs donnés et la dernière activité."""
    job_id = nouveau_job(jobs)
    avant = jobs.find_one({"_id": job_id})["maj_le"]

    assert file_jobs.mettre_a_jour(jobs, job_id, pid=1234, dossier="/runs/1") is True

    job = jobs.find_one({"_id": job_id})
    assert job["pid"] == 1234
    assert job["dossier"] == "/runs/1"
    assert job["maj_le"] >= avant


def test_mettre_a_jour_job_inconnu_renvoie_false(jobs):
    """Mettre à jour un job qui n'existe pas ne plante pas."""
    assert file_jobs.mettre_a_jour(jobs, ObjectId(), pid=1) is False
    assert file_jobs.mettre_a_jour(jobs, "invalide", pid=1) is False


def test_terminer_job_note_l_etat_le_message_et_la_date(jobs):
    """terminer_job enregistre l'état final, le message et l'heure de fin."""
    job_id = nouveau_job(jobs)

    file_jobs.terminer_job(jobs, job_id, file_jobs.ERREUR, "Quelque chose a échoué")

    job = jobs.find_one({"_id": job_id})
    assert job["etat"] == file_jobs.ERREUR
    assert job["message"] == "Quelque chose a échoué"
    assert job["termine_le"] is not None


def test_terminer_job_refuse_un_etat_qui_n_est_pas_final(jobs):
    """On ne peut pas "terminer" un job avec l'état "en cours"."""
    job_id = nouveau_job(jobs)

    with pytest.raises(ValueError):
        file_jobs.terminer_job(jobs, job_id, file_jobs.EN_COURS)


def test_marquer_interrompus_ne_touche_que_les_jobs_en_cours(jobs):
    """Au démarrage du worker, seuls les jobs "en cours" deviennent "interrompu"."""
    en_cours = nouveau_job(jobs)
    file_jobs.reserver_prochain_job(jobs)
    en_attente = nouveau_job(jobs)
    fini = nouveau_job(jobs)
    file_jobs.terminer_job(jobs, fini, file_jobs.TERMINE)

    assert file_jobs.marquer_interrompus(jobs) == 1

    assert jobs.find_one({"_id": en_cours})["etat"] == file_jobs.INTERROMPU
    assert jobs.find_one({"_id": en_cours})["termine_le"] is not None
    assert jobs.find_one({"_id": en_attente})["etat"] == file_jobs.EN_ATTENTE
    assert jobs.find_one({"_id": fini})["etat"] == file_jobs.TERMINE