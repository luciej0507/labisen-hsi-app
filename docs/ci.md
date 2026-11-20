# Documentation de la chaîne d'intégration continue (CI)

Projet : application SpectraVision (LabISEN, imagerie hyperspectrale).
Dernière mise à jour : 20/11/2026.

## 1. Objectif

La chaîne d'intégration continue vérifie automatiquement, à chaque modification du code, que les tests passent. Elle s'exécute sur une machine vierge fournie par GitHub, sans fichier `.env`, sans serveur SFTP, sans base MongoDB réelle et sans GPU. Un test qui réussit dans ces conditions ne dépend donc pas de la machine du développeur.

## 2. Outils et justification

| Outil | Rôle |
|---|---|
| GitHub Actions | Exécute la chaîne à chaque push et à chaque pull request |
| pytest | Lance les tests automatisés du dossier `tests/` |
| pytest-cov | Mesure la couverture du code du dossier `modules/` |
| mongomock | Remplace MongoDB par une base factice en mémoire pendant les tests |

Justification du choix de GitHub Actions : le code du projet est déjà hébergé sur GitHub. La chaîne est donc intégrée au dépôt sans service externe à installer, à configurer ni à payer, et son résultat s'affiche directement sur les commits et les pull requests.

Les dépendances de machine learning (`requirements-ml.txt` : torch, anomalib, mlflow) ne sont pas installées en CI. Elles sont lourdes et inutiles pour les tests actuels, qui portent sur le code applicatif.

## 3. Fichier de configuration

La chaîne est décrite dans le fichier `.github/workflows/ci.yml`. Il est versionné avec les sources sur le dépôt distant. GitHub le détecte automatiquement grâce à son emplacement, qui est imposé.

## 4. Déclencheurs

| Événement | Effet |
|---|---|
| Push sur n'importe quelle branche | La chaîne se lance |
| Ouverture ou mise à jour d'une pull request | La chaîne se lance |
| Simple commit local, sans push | Rien ne se passe : GitHub ne connaît pas encore le commit |

Aucun filtre n'est appliqué : la chaîne se lance même si les tests n'ont pas été modifiés, car un changement dans `modules/` peut casser un test existant.

## 5. Étapes de la chaîne

Le travail s'exécute dans un seul job, nommé `tests`, sur une machine `ubuntu-latest`. Les étapes sont exécutées dans l'ordre suivant. Si l'une échoue, la chaîne s'arrête et le job est signalé en échec.

| N° | Étape | Description |
|---|---|---|
| 1 | Récupérer le code | Télécharge le dépôt sur la machine (`actions/checkout`) |
| 2 | Installer Python | Installe Python 3.12, avec un cache pip pour accélérer les exécutions suivantes (`actions/setup-python`) |
| 3 | Installer les dépendances | Met à jour pip, puis installe `requirements-dev.txt` |
| 4 | Lancer les tests | Exécute `python -m pytest -q --cov=modules --cov-report=term --cov-report=xml` |
| 5 | Publier le rapport de couverture | Enregistre `coverage.xml` comme fichier téléchargeable, même si les tests ont échoué (`actions/upload-artifact`) |

Une exécution complète dure environ 40 secondes.

## 6. Installation et configuration

Aucune installation n'est nécessaire côté GitHub : la chaîne fonctionne dès que le fichier `.github/workflows/ci.yml` est présent sur le dépôt.

Fichiers de dépendances :

- `requirements.txt` : dépendances de l'application ;
- `requirements-dev.txt` : inclut `requirements.txt`, puis ajoute `pytest`, `pytest-cov` et `mongomock`.

Aucun secret n'est nécessaire à la CI. Les tests doivent rester indépendants du fichier `.env` : par exemple, `MODE_LOCAL` est forcé à `False` dans les tests du module SFTP.

## 7. Procédure de test en local

Avant de pousser, il est conseillé de simuler la machine vierge de la CI :

1. Renommer temporairement le fichier `.env` en `.env.bak`.
2. Créer un environnement virtuel vide et l'activer.
3. Installer les dépendances : `pip install -r requirements-dev.txt`.
4. Lancer les tests : `python -m pytest -q --cov=modules`.
5. Désactiver l'environnement virtuel et restaurer le `.env`.

Commandes correspondantes (Linux) :

```
mv .env .env.bak
python3 -m venv /tmp/venv-ci
source /tmp/venv-ci/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q --cov=modules
deactivate
mv .env.bak .env
```

Si cette procédure réussit, la CI réussit presque toujours.

## 8. Consulter le résultat

1. Ouvrir le dépôt sur GitHub, onglet **Actions**.
2. Cliquer sur l'exécution voulue, puis sur le job `tests`.
3. Chaque étape affiche son état (réussie ou en échec) et ses messages détaillés.
4. Le rapport `rapport-couverture` est téléchargeable en bas de la page de l'exécution.

Un état est aussi affiché à côté de chaque commit et en bas de chaque pull request.

## 9. Protection de la branche `main`

La branche `main` est protégée par les règles suivantes :

- toute modification passe par une pull request (pas de push direct) ;
- le contrôle `tests` doit être réussi pour pouvoir fusionner ;
- la règle s'applique aussi aux administrateurs du dépôt.


## 10. Résolution des problèmes courants

| Symptôme | Cause probable | Solution |
|---|---|---|
| `ModuleNotFoundError` en CI, mais pas en local | Une bibliothèque manque dans `requirements.txt` ou `requirements-dev.txt` | L'ajouter au bon fichier |
| Un test réussit en local et échoue en CI | Le test dépend du `.env` ou d'un fichier de la machine | Isoler le test (`monkeypatch`, `tmp_path`) |
| `unrecognized arguments: --cov` en local | `pytest-cov` n'est pas installé | `pip install -r requirements-dev.txt` |
| Le contrôle `tests` n'apparaît pas dans la protection de branche | La CI n'a jamais tourné | Pousser un commit, attendre la fin de l'exécution, puis revenir au réglage |

## 11. Limites connues et évolutions prévues

- La couverture de `modules/` était d'environ 51 % lors de la première mise en place. Le code d'apprentissage (patching, entraînement, serveur) n'est pas encore testé : il fait l'objet de la compétence C12.
- La chaîne ne contient pas encore de contrôle de qualité de code (`ruff`) ni d'analyse de sécurité des dépendances (`pip-audit`, `bandit`). Ils seront ajoutés dans une prochaine version.
- La chaîne de livraison continue de l'application (images Docker, publication) fait l'objet d'un document séparé (compétence C19).

## 12. Accessibilité du document

Ce document est rédigé en Markdown avec une hiérarchie de titres, des tableaux simples (une ligne d'en-tête, pas de cellules fusionnées) et aucune information transmise par la couleur seule. Il ne contient pas d'image. Il peut être converti en HTML ou en PDF balisé.