# Application HSI (ISEN / LabISEN)

## Prérequis

- Python 3.10 ou plus récent
- Docker et Docker Compose (pour MongoDB)

## Installation

### 1. Cloner le dépôt

```bash
git clone https://github.com/luciej0507/labisen-hsi-app.git
cd labisen-hsi-app
```

### 2. Créer et activer l'environnement virtuel

```bash
python -m venv .venv

# Linux, Mac ou WSL
source .venv/bin/activate

# Windows (PowerShell)
.venv\Scripts\activate
```

### 3. Installer les dépendances

```bash
# Pour le développement (inclut les outils de test)
pip install -r requirements-dev.txt

# Pour la production
pip install -r requirements.txt
```

### 4. Configurer les variables d'environnement

Copier le modèle puis adapter les valeurs :

```bash
cp .env.example .env
```

Variables principales (détail dans `.env.example`) :

- `MONGO_URI` et `MONGO_DB_NAME` : connexion à MongoDB.
- `DATASETS_PATH` : dossier du serveur qui contient les datasets (chemin absolu). L'application tourne sur le serveur et lit directement ce dossier.
- `MLFLOW_URL_INTERNE` : adresse de MLflow utilisée par le worker.
- `MLFLOW_URL_PUBLIQUE` : adresse de MLflow ouverte dans le navigateur (lien affiché dans l'interface). À remplacer par l'adresse du serveur.
- `MLFLOW_DEMARRAGE_AUTO` : `1` pour que le worker démarre MLflow, `0` si MLflow est lancé à part.
- `DOSSIER_DONNEES_APP` (facultatif) : dossier des fichiers de suivi du patching et des entraînements, vu à la fois par l'application et par le worker.

### 5. Lancer MongoDB

```bash
docker compose up -d
```

Vérifier que le conteneur tourne avec `docker ps` (le conteneur `isen_hsi_mongo` doit être "Up").

### 6. Créer le compte administrateur (une seule fois)

```bash
python scripts/init_admin.py
```

Le script demande un nom d'utilisateur et un mot de passe. Si un admin existe déjà, il ne fait rien.

### 7. Lancer l'application

```bash
streamlit run app.py
```

L'application est alors disponible sur http://localhost:8501.

### 8. Lancer le worker (patching et entraînement)

Les calculs lourds sont exécutés par un programme séparé, le worker, qui lit la file d'attente de jobs dans MongoDB. Il se lance sur la machine qui possède les GPU, avec les bibliothèques d'apprentissage :

```bash
pip install -r requirements-ml.txt
python worker.py
```

Pour l'arrêter proprement : `Ctrl+C`.