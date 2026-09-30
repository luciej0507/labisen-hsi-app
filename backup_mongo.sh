#!/bin/bash
# Sauvegarde de la base MongoDB du conteneur Docker vers le dossier ./dump_mongo

# À faire une seule fois : rendre le script exécutable
# chmod +x backup.sh
# Lancer une sauvegarde (conteneur Mongo démarré)
# ./backup.sh

# Paramètres à modifier si besoin
CONTENEUR="isen_hsi_mongo"
BASE="labisen_hsi_app"
DOSSIER="./dump_mongo"

# Arrêter le script dès qu'une commande échoue
set -e

# 1. Supprimer un éventuel ancien dossier temporaire dans le conteneur
docker exec "$CONTENEUR" rm -rf /dump

# 2. Exporter la base dans le conteneur (dossier temporaire /dump)
docker exec "$CONTENEUR" mongodump --db "$BASE" --out /dump

# 3. Supprimer l'ancienne sauvegarde locale (évite un sous-dossier imbriqué)
#    Cette étape n'est atteinte que si l'export a réussi
rm -rf "$DOSSIER"

# 4. Copier l'export du conteneur vers le projet
docker cp "$CONTENEUR":/dump "$DOSSIER"

# 5. Nettoyer le dossier temporaire dans le conteneur
docker exec "$CONTENEUR" rm -rf /dump

echo "Sauvegarde terminée dans $DOSSIER"