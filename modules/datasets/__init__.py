"""
modules/datasets/__init__.py

Package de gestion des datasets du serveur de l'école.

L'application tourne sur le même serveur que les datasets : les modules de
ce package lisent et écrivent directement sur le disque.

Organisation du package :
  - chemins.py : racine des datasets (DATASETS_PATH) et utilitaires de dossiers
  - exploration_dataset.py : parcours de l'arborescence et droits d'accès
  - stats.py : conformité d'un dataset, cubes et dimensions
  - upload.py : envoi d'une archive zip et ajout de l'accès en base
"""
