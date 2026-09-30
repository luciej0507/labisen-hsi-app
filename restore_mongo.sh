#!/bin/bash
# Restauration de la base MongoDB depuis le dossier ./dump_mongo vers le conteneur Docker


# À faire une seule fois : rendre le script exécutable
# chmod +x restore.sh
# Lancer une restauration (conteneur Mongo démarré)
# ./restore.sh


# Paramètres à modifier si besoin
CONTENEUR="isen_hsi_mongo"
BASE="labisen_hsi_app"
DOSSIER="./dump_mongo"

# Arrêter le script dès qu'une commande échoue
set -e

# Vérifier que la sauvegarde existe avant de commencer
if [ ! -d "$DOSSIER/$BASE" ]; then
  echo "Erreur : le dossier $DOSSIER/$BASE est introuvable."
  exit 1
fi

# 1. Supprimer un éventuel ancien dossier temporaire dans le conteneur
docker exec "$CONTENEUR" rm -rf /dump

# 2. Copier la sauvegarde du projet vers le conteneur
docker cp "$DOSSIER" "$CONTENEUR":/dump

# 3. Restaurer uniquement la base de l'application
#    Les documents sont ajoutés sans rien écraser (pas d'option --drop)
docker exec "$CONTENEUR" mongorestore /dump --nsInclude "$BASE.*"

# 4. Nettoyer le dossier temporaire dans le conteneur
docker exec "$CONTENEUR" rm -rf /dump

echo "Restauration terminée depuis $DOSSIER"