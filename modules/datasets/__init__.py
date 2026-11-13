"""
modules/datasets/__init__.py

Package de gestion des datasets du serveur de l'école.

Organisation du package :
  - sftp.py : connexion SFTP partagée et utilitaires bas niveau
  - exploration_dataset.py : parcours de l'arborescence et droits d'accès
  - stats.py : conformité d'un dataset, cubes et dimensions
  - upload.py : envoi d'une archive zip et ajout de l'accès en base
"""