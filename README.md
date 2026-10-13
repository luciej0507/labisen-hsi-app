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